import re

import pytest
from rest_framework.throttling import ScopedRateThrottle

from apps.accounts.models import OTPRequest, User

from .helpers import PHONE, post, sign_up, verified_user

pytestmark = pytest.mark.django_db


class FailingBackend:
    def send(self, *, target, code, purpose):
        raise RuntimeError("SMS gateway is down")


# --- register -----------------------------------------------------------------------------------------
def test_register_sends_an_otp_and_creates_an_unverified_user(api_client, otp_outbox):
    response = sign_up(api_client)
    body = response.json()

    assert response.status_code == 200
    assert body["success"] is True
    assert body["message"] == "OTP sent to +88017****5678."
    token = body["data"]["token"]
    assert re.fullmatch(r"[A-Za-z0-9_-]{20,}", token)  # URL-safe: the frontend puts it in the path

    user = User.objects.get(phone_number=PHONE)
    assert user.name == "Rahim" and not user.is_phone_verified and not user.has_usable_password()
    assert len(otp_outbox) == 1
    assert otp_outbox[0].target == PHONE and re.fullmatch(r"\d{6}", otp_outbox[0].code)


def test_raw_token_and_code_are_never_stored(api_client, otp_outbox):
    token = sign_up(api_client).json()["data"]["token"]
    otp = OTPRequest.objects.get()
    assert otp.token_hash != token and token not in otp.token_hash
    assert otp_outbox[0].code not in otp.code_hash and len(otp.code_hash) == 64


def test_register_requires_a_name_and_a_valid_phone(api_client):
    response = post(api_client, "register", {"phone_number": "01712345678"})
    body = response.json()
    assert response.status_code == 400
    assert set(body["field_errors"]) == {"name", "phone_number"}
    assert isinstance(body["errors"], list) and isinstance(body["error"], str)
    assert not User.objects.exists()


def test_register_rejects_an_already_verified_phone(api_client, otp_outbox):
    verified_user()
    response = sign_up(api_client)
    assert response.status_code == 400
    assert response.json()["errors"] == ["Phone number: A user with this phone number already exists."]
    assert otp_outbox == []


def test_register_again_before_verifying_reuses_the_user_and_supersedes_the_old_otp(
    api_client, otp_outbox
):
    first_token = sign_up(api_client, name="Old Name").json()["data"]["token"]
    second_token = sign_up(api_client, name="New Name").json()["data"]["token"]

    assert User.objects.count() == 1 and User.objects.get().name == "New Name"
    assert first_token != second_token and len(otp_outbox) == 2
    assert OTPRequest.objects.filter(consumed_at__isnull=True).count() == 1


def test_email_is_optional_normalised_and_unique(api_client):
    assert sign_up(api_client, email="").status_code == 200
    assert User.objects.get().email is None

    assert sign_up(api_client, phone="+8801722222222", email="Rahim@Example.com").status_code == 200
    assert User.objects.get(phone_number="+8801722222222").email == "rahim@example.com"

    clash = sign_up(api_client, phone="+8801733333333", email="RAHIM@example.com")
    assert clash.status_code == 400
    assert clash.json()["errors"] == ["Email: A user with this email already exists."]


def test_register_answers_503_and_leaves_nothing_behind_when_delivery_fails(api_client, settings):
    settings.OTP_BACKEND = f"{FailingBackend.__module__}.FailingBackend"
    response = sign_up(api_client)
    assert response.status_code == 503
    assert response.json()["success"] is False
    assert "gateway" not in response.content.decode().lower()  # provider details don't leak
    assert not User.objects.exists() and not OTPRequest.objects.exists()


# --- login --------------------------------------------------------------------------------------------
def test_login_sends_an_otp_to_a_verified_user(api_client, otp_outbox):
    verified_user()
    # the frontend also sends `expiresInMins`
    response = post(api_client, "login", {"phone_number": PHONE, "expiresInMins": 1})
    assert response.status_code == 200
    assert response.json()["data"]["token"]
    assert otp_outbox[0].target == PHONE and otp_outbox[0].purpose == "login"


def test_login_works_without_the_trailing_slash(api_client):
    verified_user()
    response = api_client.post("/api/v1/accounts/login", {"phone_number": PHONE})
    assert response.status_code == 200


def test_login_unknown_number(api_client, otp_outbox):
    response = post(api_client, "login", {"phone_number": PHONE})
    assert response.status_code == 400
    assert "No account found" in response.json()["error"]
    assert otp_outbox == []


def test_login_before_the_number_was_ever_verified(api_client, otp_outbox):
    User.objects.create_user(PHONE, name="Rahim")
    response = post(api_client, "login", {"phone_number": PHONE})
    assert response.status_code == 400
    assert "not been verified" in response.json()["error"]
    assert otp_outbox == []


def test_login_for_a_disabled_account(api_client, otp_outbox):
    verified_user(is_active=False)
    response = post(api_client, "login", {"phone_number": PHONE})
    assert response.status_code == 400
    assert response.json()["errors"] == ["This account is disabled."]
    assert otp_outbox == []


# --- rate limiting ------------------------------------------------------------------------------------
def test_a_phone_number_can_only_request_a_few_otps_per_hour(api_client, otp_outbox, settings):
    settings.OTP_MAX_REQUESTS_PER_TARGET_PER_HOUR = 3
    for _ in range(3):
        assert sign_up(api_client).status_code == 200
    blocked = sign_up(api_client)
    assert blocked.status_code == 429
    assert 1 <= int(blocked["Retry-After"]) <= 3600
    assert blocked.json()["success"] is False
    assert len(otp_outbox) == 3  # the blocked request sent nothing


def test_otp_sending_is_throttled_per_client_ip(api_client, monkeypatch):
    monkeypatch.setitem(ScopedRateThrottle.THROTTLE_RATES, "otp_send", "2/min")
    assert sign_up(api_client, phone="+8801711111111").status_code == 200
    assert sign_up(api_client, phone="+8801722222222").status_code == 200
    third = sign_up(api_client, phone="+8801733333333")
    assert third.status_code == 429 and "Retry-After" in third
