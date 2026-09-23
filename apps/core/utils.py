"""Small helpers shared by every app."""


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
