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
