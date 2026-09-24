"""What happens to a request that is too big: a 413 (or 400) in the usual envelope, never a 500, and an upload over
the ceiling is refused before a view or a parser touches it."""
import json
import logging

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from .urls import EchoView

pytestmark = pytest.mark.urls("apps.core.tests.urls")

ECHO = "/api/v1/_t/echo/"
MB = 1024 * 1024


@pytest.fixture(autouse=True)
def _count_from_zero():
    EchoView.hits = 0


def file_of(size, name="clip.bin"):
    return SimpleUploadedFile(name, b"x" * size)


def no_bug_was_logged(caplog):
    return not [record for record in caplog.records if record.levelno >= logging.ERROR]


# --- a body over DATA_UPLOAD_MAX_MEMORY_SIZE -------------------------------------------------------------------------
def test_a_json_body_over_the_limit_is_a_413_in_the_envelope_and_not_a_bug(api_client, settings, caplog):
    settings.DATA_UPLOAD_MAX_MEMORY_SIZE = 1000

    response = api_client.post(ECHO, {"name": "x" * 5000}, format="json")

    assert response.status_code == 413
    body = response.json()
    assert body["success"] is False and body["message"] == "Request too large."
    assert no_bug_was_logged(caplog)


def test_a_json_body_under_the_limit_goes_through(api_client, settings):
    settings.DATA_UPLOAD_MAX_MEMORY_SIZE = 10_000
    response = api_client.post(ECHO, {"name": "x" * 5000}, format="json")
    assert response.status_code == 200 and response.json()["data"] == {"fields": ["name"]}


def test_too_many_form_fields_is_a_400_and_not_a_bug(api_client, settings, caplog):
    settings.DATA_UPLOAD_MAX_NUMBER_FIELDS = 3

    response = api_client.post(ECHO, {f"field{n}": "v" for n in range(6)}, format="multipart")

    assert response.status_code == 400
    assert response.json()["success"] is False
    assert no_bug_was_logged(caplog)


# --- an upload over MAX_UPLOAD_REQUEST_MB -----------------------------------------------------------------------------
def test_an_upload_over_the_ceiling_is_refused_before_the_view_runs(api_client, settings):
    settings.MAX_UPLOAD_REQUEST_MB = 1

    response = api_client.post(ECHO, {"media": file_of(2 * MB)}, format="multipart")

    assert response.status_code == 413
    body = response.json()
    assert body["success"] is False and body["message"] == "Request too large."
    assert "1 MB" in body["error"]
    assert EchoView.hits == 0


def test_the_413_carries_the_cors_headers_so_the_browser_can_read_it(api_client, settings):
    settings.MAX_UPLOAD_REQUEST_MB = 1
    settings.CORS_ALLOWED_ORIGINS = ["https://shop.example"]

    response = api_client.post(ECHO, {"media": file_of(2 * MB)}, format="multipart", HTTP_ORIGIN="https://shop.example")

    assert response.status_code == 413
    assert response["Access-Control-Allow-Origin"] == "https://shop.example"


def test_an_upload_under_the_ceiling_goes_through(api_client, settings):
    settings.MAX_UPLOAD_REQUEST_MB = 1
    response = api_client.post(ECHO, {"media": file_of(100_000), "note": "hi"}, format="multipart")
    assert response.status_code == 200 and response.json()["data"] == {"fields": ["media", "note"]}
    assert EchoView.hits == 1


def test_the_ceiling_is_about_uploads_not_json(api_client, settings):
    """A JSON body is bounded by DATA_UPLOAD_MAX_MEMORY_SIZE, not by the (much larger) upload ceiling."""
    settings.MAX_UPLOAD_REQUEST_MB = 1
    settings.DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * MB
    response = api_client.post(ECHO, {"name": "x" * (2 * MB)}, format="json")
    assert response.status_code == 200


def test_only_api_paths_are_checked(api_client, settings):
    """The admin (trusted staff uploading product videos) is not held to the API's ceiling."""
    settings.MAX_UPLOAD_REQUEST_MB = 1
    response = api_client.post("/somewhere/else/", {"media": file_of(2 * MB)}, format="multipart")
    assert response.status_code == 404  # unknown path: it got as far as the router


def test_a_garbage_content_length_is_not_a_crash(api_client, settings):
    settings.MAX_UPLOAD_REQUEST_MB = 1
    response = api_client.generic(
        "POST", ECHO, b"", content_type="multipart/form-data; boundary=x", CONTENT_LENGTH="not-a-number"
    )
    assert response.status_code != 413 and response.status_code < 500
    assert isinstance(json.loads(response.content), dict)
