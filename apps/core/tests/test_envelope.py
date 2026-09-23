import pytest
from django.db import OperationalError

pytestmark = pytest.mark.urls("apps.core.tests.urls")


def test_success_is_wrapped_with_custom_message_and_status(api_client):
    response = api_client.post("/api/v1/_t/validate/", {"phone_number": "+8801712345678", "quantity": 2})
    assert response.status_code == 201
    assert response.json() == {"success": True, "message": "Order placed", "data": {"id": 1}}


def test_success_default_message_and_list_data(api_client):
    response = api_client.get("/api/v1/_t/plain/")
    assert response.status_code == 200
    assert response.json() == {"success": True, "message": "OK", "data": [1, 2, 3]}


def test_validation_error_has_error_errors_and_field_errors(api_client):
    response = api_client.post("/api/v1/_t/validate/", {"quantity": 0})
    body = response.json()
    assert response.status_code == 400
    assert body["success"] is False
    assert body["message"] == "Validation failed."
    # the frontend needs `errors` to be an array of strings and `error` to be a plain string
    assert isinstance(body["errors"], list) and all(isinstance(e, str) for e in body["errors"])
    assert isinstance(body["error"], str) and body["error"] == body["errors"][0]
    assert "Phone number: This field is required." in body["errors"]
    assert set(body["field_errors"]) == {"phone_number", "quantity"}


def test_missing_token_is_401_envelope_with_www_authenticate(api_client):
    response = api_client.get("/api/v1/_t/protected/")
    body = response.json()
    assert response.status_code == 401
    assert response["WWW-Authenticate"].startswith("Bearer")
    assert body["success"] is False and body["message"] == "Authentication failed."
    assert body["errors"] == ["Authentication credentials were not provided."]


def test_garbage_token_is_401_envelope(api_client):
    api_client.credentials(HTTP_AUTHORIZATION="Bearer not-a-real-token")
    response = api_client.get("/api/v1/_t/protected/")
    body = response.json()
    assert response.status_code == 401
    assert body["success"] is False
    assert isinstance(body["errors"], list) and len(body["errors"]) == 1
    assert isinstance(body["error"], str)


def test_method_not_allowed_is_enveloped(api_client):
    response = api_client.get("/api/v1/_t/validate/")
    assert response.status_code == 405
    assert response.json()["message"] == "Method not allowed."


def test_unhandled_exception_is_500_envelope_without_leaking_details(api_client):
    response = api_client.get("/api/v1/_t/boom/")
    assert response.status_code == 500
    assert response.json()["success"] is False
    assert "secret internal detail" not in response.content.decode()


def test_unknown_api_path_is_json_404(api_client):
    response = api_client.get("/api/v1/nope/")
    assert response.status_code == 404
    assert response.json() == {
        "success": False,
        "message": "Not found.",
        "error": "Not found.",
        "errors": ["Not found."],
    }


@pytest.mark.urls("config.urls")
@pytest.mark.parametrize("debug", [False, True])
@pytest.mark.parametrize("method", ["get", "post", "put", "patch", "delete"])
def test_unknown_api_path_is_json_404_in_debug_and_prod(api_client, settings, debug, method):
    settings.DEBUG = debug  # Django's handler404 is bypassed by the HTML debug page when DEBUG=True
    response = getattr(api_client, method)("/api/v1/does/not/exist")
    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/json")
    assert response.json()["success"] is False and response.json()["errors"] == ["Not found."]


def test_unknown_non_api_path_keeps_django_html_404(api_client):
    response = api_client.get("/somewhere-else/")
    assert response.status_code == 404
    assert response["Content-Type"].startswith("text/html")


@pytest.mark.urls("config.urls")
def test_health_reports_503_envelope_when_database_is_down(api_client, monkeypatch):
    class BrokenConnection:
        def cursor(self):
            raise OperationalError("connection refused")

    monkeypatch.setattr("apps.core.views.connection", BrokenConnection())
    response = api_client.get("/api/v1/health/")
    assert response.status_code == 503
    assert response.json()["success"] is False
    assert response.json()["errors"] == ["Database is unavailable."]


@pytest.mark.urls("config.urls")
@pytest.mark.django_db
def test_health_ok(api_client):
    response = api_client.get("/api/v1/health/")
    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "message": "OK",
        "data": {"status": "ok", "database": "ok"},
    }
