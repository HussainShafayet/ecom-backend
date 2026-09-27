"""Small helpers shared by every app."""
from django.core.files.storage import default_storage


def absolute_url(request, file):
    """Absolute URL of a stored file (a FieldFile or a bare storage name), or None when there is none.
    The frontend lives on another origin, so a media URL is never relative."""
    name = getattr(file, "name", file)
    if not name:
        return None
    url = default_storage.url(name)
    return request.build_absolute_uri(url) if request is not None else url


def mask_phone(phone):
    """+8801712345678 -> +88017****5678 (for messages and logs; never log a full number)."""
    if not phone or len(phone) < 11:
        return "****"
    return f"{phone[:6]}{'*' * (len(phone) - 10)}{phone[-4:]}"


def mask_email(email):
    """rahim@example.com -> r***@example.com"""
    if not email or "@" not in email:
        return "****"
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"
