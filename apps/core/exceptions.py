"""Turns every error into the envelope the frontend reads (see errors.py for the shape)."""
import logging

from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler
from rest_framework.views import set_rollback

from .errors import build_error_envelope, flatten_errors

logger = logging.getLogger(__name__)

STATUS_MESSAGES = {
    status.HTTP_400_BAD_REQUEST: "Bad request.",
    status.HTTP_401_UNAUTHORIZED: "Authentication failed.",
    status.HTTP_403_FORBIDDEN: "Permission denied.",
    status.HTTP_404_NOT_FOUND: "Not found.",
    status.HTTP_405_METHOD_NOT_ALLOWED: "Method not allowed.",
    status.HTTP_406_NOT_ACCEPTABLE: "Not acceptable.",
    status.HTTP_409_CONFLICT: "Conflict.",
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: "Unsupported media type.",
    status.HTTP_429_TOO_MANY_REQUESTS: "Too many requests.",
    status.HTTP_503_SERVICE_UNAVAILABLE: "Service unavailable.",
}

__all__ = [
    "ServiceUnavailable",
    "build_error_envelope",
    "envelope_exception_handler",
    "flatten_errors",
]


class ServiceUnavailable(exceptions.APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Service temporarily unavailable."
    default_code = "service_unavailable"


def envelope_exception_handler(exc, context):
    response = drf_exception_handler(exc, context)

    if response is None:  # not a DRF/Django-handled error -> a real bug
        request = context.get("request")
        logger.error("Unhandled exception on %s", getattr(request, "path", "?"), exc_info=exc)
        set_rollback()
        return Response(
            build_error_envelope("Internal server error.", ["Something went wrong on our side."]),
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    errors, field_errors = flatten_errors(response.data)
    if isinstance(exc, exceptions.ValidationError):
        message = "Validation failed."
    else:
        message = STATUS_MESSAGES.get(response.status_code, "Request failed.")
    # Mutating (not replacing) the response keeps headers such as Retry-After / WWW-Authenticate.
    response.data = build_error_envelope(message, errors, field_errors)
    return response
