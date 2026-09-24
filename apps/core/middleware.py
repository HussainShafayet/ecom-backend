"""Request-level guards that run before any view (or body parser) does."""
from django.conf import settings
from django.http import JsonResponse

from .errors import build_error_envelope


class UploadSizeLimitMiddleware:
    """Refuses an API upload whose declared size is over `MAX_UPLOAD_REQUEST_MB` with a 413, before a byte of it is
    read. Django keeps an upload in a temporary file until a view rejects it, and has no limit on the total size of
    the files in one request (`DATA_UPLOAD_MAX_MEMORY_SIZE` only counts the non-file fields), so without this any
    client, signed in or not, could make the server store gigabytes for a request that is refused afterwards.

    Only multipart bodies are looked at, and only under /api/ (the staff uploading in the admin are trusted).
    Every other body is bounded by `DATA_UPLOAD_MAX_MEMORY_SIZE`. Sits under CorsMiddleware, so the 413 carries the
    CORS headers and the browser shows the error instead of a CORS failure. The reverse proxy should enforce the same
    ceiling (`client_max_body_size` in nginx): it stops the transfer itself, this only answers the request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/api/") and request.META.get("CONTENT_TYPE", "").startswith("multipart/"):
            try:
                size = int(request.META.get("CONTENT_LENGTH") or 0)
            except ValueError:
                size = 0
            if size > settings.MAX_UPLOAD_REQUEST_MB * 1024 * 1024:
                return JsonResponse(
                    build_error_envelope(
                        "Request too large.",
                        [f"The upload is larger than the {settings.MAX_UPLOAD_REQUEST_MB} MB the server accepts."],
                    ),
                    status=413,
                )
        return self.get_response(request)
