import logging

import pytest
from django.core.exceptions import RequestDataTooBig, SuspiciousFileOperation, TooManyFieldsSent, TooManyFilesSent
from django.http import Http404
from rest_framework.exceptions import Throttled, ValidationError

from apps.core.errors import build_error_envelope, flatten_errors
from apps.core.exceptions import envelope_exception_handler


def test_flatten_nested_and_non_field_errors():
    detail = {
        "phone_number": ["Required."],
        "items": [{"quantity": ["Too low."]}, {}],
        "non_field_errors": ["Bad combination."],
    }
    errors, field_errors = flatten_errors(detail)
    assert errors == ["Phone number: Required.", "Items 0 quantity: Too low.", "Bad combination."]
    assert field_errors == {"phone_number": ["Required."], "items.0.quantity": ["Too low."]}


def test_flatten_plain_list_and_string():
    assert flatten_errors(["Bad OTP."]) == (["Bad OTP."], {})
    assert flatten_errors("Nope.") == (["Nope."], {})


def test_flatten_simplejwt_shaped_detail():
    detail = {
        "detail": "Given token not valid for any token type",
        "code": "token_not_valid",
        "messages": [{"token_class": "AccessToken", "message": "Token is expired"}],
    }
    assert flatten_errors(detail) == (["Given token not valid for any token type"], {})


def test_build_error_envelope_defaults_errors_to_message():
    assert build_error_envelope("Boom.") == {
        "success": False,
        "message": "Boom.",
        "error": "Boom.",
        "errors": ["Boom."],
    }


def test_handler_validation_error():
    response = envelope_exception_handler(ValidationError({"otp": ["Invalid OTP."]}), {})
    assert response.status_code == 400
    assert response.data["message"] == "Validation failed."
    assert response.data["errors"] == ["OTP: Invalid OTP."]  # acronyms keep their capitals
    assert response.data["field_errors"] == {"otp": ["Invalid OTP."]}


def test_handler_throttled_keeps_retry_after_header():
    response = envelope_exception_handler(Throttled(wait=30), {})
    assert response.status_code == 429
    assert response["Retry-After"] == "30"
    assert response.data["message"] == "Too many requests."
    assert "30 seconds" in response.data["error"]


def test_handler_django_404():
    response = envelope_exception_handler(Http404(), {})
    assert response.status_code == 404
    assert response.data["message"] == "Not found."


def test_handler_unhandled_exception_is_generic_500(caplog):
    response = envelope_exception_handler(RuntimeError("db password is hunter2"), {})
    assert response.status_code == 500
    assert response.data["message"] == "Internal server error."
    assert "hunter2" not in str(response.data)
    assert "Unhandled exception" in caplog.text  # ...but the traceback is logged for us


def test_handler_a_body_over_the_limit_is_a_413_and_no_bug(caplog):
    with caplog.at_level(logging.WARNING):
        response = envelope_exception_handler(RequestDataTooBig("Request body exceeded the limit."), {})
    assert response.status_code == 413
    assert response.data["success"] is False and response.data["message"] == "Request too large."
    assert response.data["errors"] == ["The request is larger than the server accepts."]
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]  # the client's doing, not a bug
    assert "Refused a request" in caplog.text


@pytest.mark.parametrize("exc", [TooManyFieldsSent("x"), TooManyFilesSent("x"), SuspiciousFileOperation("../../etc")])
def test_handler_other_things_django_refuses_are_a_400_and_no_bug(exc, caplog):
    with caplog.at_level(logging.WARNING):
        response = envelope_exception_handler(exc, {})
    assert response.status_code == 400
    assert response.data["message"] == "Bad request."
    assert "etc" not in str(response.data)  # what the client sent is never echoed back
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]
