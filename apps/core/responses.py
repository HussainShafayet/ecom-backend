from rest_framework.response import Response


def api_response(data=None, message=None, status=200, headers=None):
    """Success response; `EnvelopeJSONRenderer` wraps `data` as {success, message, data}."""
    response = Response(data, status=status, headers=headers)
    response.envelope_message = message
    return response
