from rest_framework.renderers import JSONRenderer

from .errors import build_error_envelope, flatten_errors

DEFAULT_MESSAGES = {200: "OK", 201: "Created"}


class EnvelopeJSONRenderer(JSONRenderer):
    """Wraps every successful payload as {success, message, data}.

    Views just return `Response(data)` (or `api_response(data, message=...)`); nothing hand-builds the
    envelope. Error responses are already enveloped by `envelope_exception_handler`.
    """

    def render(self, data, accepted_media_type=None, renderer_context=None):
        response = (renderer_context or {}).get("response")
        if response is None or response.status_code == 204:
            return super().render(data, accepted_media_type, renderer_context)

        if response.status_code >= 400:
            # Safety net for a view that returned Response(..., status=4xx) directly.
            if not (isinstance(data, dict) and data.get("success") is False):
                errors, field_errors = flatten_errors(data)
                data = build_error_envelope("Request failed.", errors, field_errors)
            return super().render(data, accepted_media_type, renderer_context)

        message = getattr(response, "envelope_message", None) or DEFAULT_MESSAGES.get(
            response.status_code, "OK"
        )
        envelope = {"success": True, "message": message, "data": data}
        return super().render(envelope, accepted_media_type, renderer_context)
