"""drf-spectacular hooks so the generated OpenAPI document matches the real wire format."""

HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}

ERROR_ENVELOPE = {
    "type": "object",
    "required": ["success", "message", "error", "errors"],
    "properties": {
        "success": {"type": "boolean", "example": False},
        "message": {"type": "string", "example": "Validation failed."},
        "error": {"type": "string", "example": "Phone number: This field is required."},
        "errors": {
            "type": "array",
            "items": {"type": "string"},
            "example": ["Phone number: This field is required."],
        },
        "field_errors": {
            "type": "object",
            "additionalProperties": {"type": "array", "items": {"type": "string"}},
        },
    },
}
ERROR_RESPONSE = {
    "description": "Error envelope",
    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorEnvelope"}}},
}


def exclude_slashless_aliases(endpoints):
    """`dual_path` registers `/x/` and `/x`; document only the canonical `/x/` form."""
    paths = {endpoint[0] for endpoint in endpoints}
    return [
        endpoint
        for endpoint in endpoints
        if endpoint[0].endswith("/") or endpoint[0] + "/" not in paths
    ]


def _envelope(data_schema):
    return {
        "type": "object",
        "required": ["success", "message", "data"],
        "properties": {
            "success": {"type": "boolean", "example": True},
            "message": {"type": "string", "example": "OK"},
            "data": data_schema,
        },
    }


def envelope_postprocessing_hook(result, generator, request, public):
    """Wrap every 2xx body as {success, message, data} and document the shared error envelope."""
    result.setdefault("components", {}).setdefault("schemas", {})["ErrorEnvelope"] = ERROR_ENVELOPE

    for path_item in result.get("paths", {}).values():
        for method, operation in path_item.items():
            if method not in HTTP_METHODS:
                continue
            responses = operation.setdefault("responses", {})
            for code, response in responses.items():
                if not str(code).startswith("2"):
                    continue
                media = response.get("content", {}).get("application/json")
                if media is not None:
                    media["schema"] = _envelope(media.get("schema", {}))
                else:  # e.g. {"success": true} style acknowledgements
                    response["content"] = {
                        "application/json": {"schema": _envelope({"type": "object", "nullable": True})}
                    }
            responses.setdefault("4XX", ERROR_RESPONSE)
            responses.setdefault("5XX", ERROR_RESPONSE)
    return result
