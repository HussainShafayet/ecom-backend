"""Pure helpers that shape the error envelope. No DRF imports on purpose: the renderer and the
exception handler both need them, and importing `rest_framework.views` from here would create an
import cycle (DRF settings -> renderer -> this module).

The frontend consumes errors in two ways: `errors` (a list of strings, rendered by <ErrorDisplay/>,
which requires Array.isArray) and `error` (a single string, read by cart/wishlist/address/review
slices). Both are always present. `field_errors` is an extra for future use.
"""

NON_FIELD_KEYS = {"detail", "non_field_errors"}


def build_error_envelope(message, errors=None, field_errors=None):
    errors = list(errors) if errors else [message]
    body = {"success": False, "message": message, "error": errors[0], "errors": errors}
    if field_errors:
        body["field_errors"] = field_errors
    return body


def _walk(detail, path):
    """Yield (path, message) for every leaf of a DRF error detail structure."""
    if isinstance(detail, dict):
        for key, value in detail.items():
            yield from _walk(value, path + (str(key),))
    elif isinstance(detail, (list, tuple)):
        for index, value in enumerate(detail):
            nested = isinstance(value, (dict, list, tuple))
            yield from _walk(value, path + (str(index),) if nested else path)
    else:
        yield path, str(detail)


def _label(path):
    return " ".join(part.replace("_", " ") for part in path).strip().capitalize()


def flatten_errors(detail):
    """Return (errors, field_errors): human readable strings and a {field: [messages]} map."""
    # simplejwt's InvalidToken/TokenError detail: {"detail": ..., "code": ..., "messages": [...]}
    if isinstance(detail, dict) and "detail" in detail and "code" in detail:
        return [str(detail["detail"])], {}

    errors, field_errors = [], {}
    for path, message in _walk(detail, ()):
        if not path or (len(path) == 1 and path[0] in NON_FIELD_KEYS):
            errors.append(message)
            continue
        errors.append(f"{_label(path)}: {message}")
        field_errors.setdefault(".".join(path), []).append(message)
    return errors, field_errors
