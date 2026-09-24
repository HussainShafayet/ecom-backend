"""Turns every error into the envelope the frontend reads (see errors.py for the shape)."""
import logging

from django.core.exceptions import RequestDataTooBig, SuspiciousOperation
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
    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE: "Request too large.",
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


def _refused_request(exc, context):
    """A `SuspiciousOperation` is something the CLIENT did that Django refuses to process: a body over
    `DATA_UPLOAD_MAX_MEMORY_SIZE`, too many form fields or files, a hostile file name. Django itself answers 400 to
    these (413 for the size); without this they would come out of DRF as a 500 and an ERROR in the log."""
    request = context.get("request")
    logger.warning("Refused a request on %s: %s", getattr(request, "path", "?"), exc)
    set_rollback()
    if isinstance(exc, RequestDataTooBig):
        return Response(
            build_error_envelope("Request too large.", ["The request is larger than the server accepts."]),
            status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )
    return Response(
        build_error_envelope("Bad request.", ["The server can not process this request."]),
        status=status.HTTP_400_BAD_REQUEST,
    )


def envelope_exception_handler(exc, context):
    response = drf_exception_handler(exc, context)

    if response is None and isinstance(exc, SuspiciousOperation):
        return _refused_request(exc, context)

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
