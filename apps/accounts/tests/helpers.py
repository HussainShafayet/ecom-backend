"""Shared by the accounts API tests. Mirrors exactly what the React app sends."""
from datetime import timedelta

from django.utils import timezone

from apps.accounts.models import OTPRequest, User

PHONE = "+8801712345678"
BASE = "/api/v1/accounts"


def post(client, path, data=None, **extra):
    return client.post(f"{BASE}/{path}/", data if data is not None else {}, **extra)


def sign_up(client, phone=PHONE, name="Rahim", **extra):
    return post(client, "register", {"phone_number": phone, "name": name, **extra})


def sign_in(client, token, code, **extra):
    return post(client, "verify-otp", {"token": token, "otp": code, **extra})


def verified_user(phone=PHONE, **extra):
    return User.objects.create_user(phone, name="Rahim", is_phone_verified=True, **extra)


def different_code(code):
    return "000000" if code != "000000" else "111111"


def expire_cooldown():
    """Pretend the last OTP was sent a while ago so a resend is allowed."""
    OTPRequest.objects.update(last_sent_at=timezone.now() - timedelta(minutes=5))


def register_and_get_code(client, otp_outbox, **kwargs):
    """Register, return (token, code) as the frontend would learn them (code from the 'SMS')."""
    response = sign_up(client, **kwargs)
    assert response.status_code == 200, response.content
    return response.json()["data"]["token"], otp_outbox[-1].code


# --- authenticated clients and uploads ------------------------------------------------------------------
import io  # noqa: E402

from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402
from PIL import Image  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

from apps.accounts.services import issue_tokens  # noqa: E402


def authed_client(user):
    """A client sending a real JWT access token, like the frontend does."""
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user)['access']}")
    return client


def image_upload(name="me.png", fmt="PNG", size=(8, 8)):
    buffer = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buffer, format=fmt)
    content_type = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp", "GIF": "image/gif"}[fmt]
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=content_type)
