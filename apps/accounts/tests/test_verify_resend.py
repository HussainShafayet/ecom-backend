from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.accounts.models import OTPRequest, User
from apps.accounts.otp.service import start_otp
from apps.accounts.signals import guest_data_received

from .helpers import (
    PHONE,
    different_code,
    expire_cooldown,
    post,
    register_and_get_code,
    sign_in,
    verified_user,
)

pytestmark = pytest.mark.django_db


# --- verify-otp ---------------------------------------------------------------------------------------
def test_verifying_the_otp_returns_working_tokens_and_marks_the_phone_verified(api_client, otp_outbox):
    token, code = register_and_get_code(api_client, otp_outbox)

    response = sign_in(api_client, token, code)
    body = response.json()

    assert response.status_code == 200 and body["success"] is True
    tokens = body["data"]["tokens"]  # exactly where the frontend reads them
    user = User.objects.get(phone_number=PHONE)
    assert user.is_phone_verified
    assert int(AccessToken(tokens["access"])["user_id"]) == user.pk
    assert RefreshToken(tokens["refresh"])  # a real, usable refresh token
    assert OTPRequest.objects.get().consumed_at is not None


def test_login_flow_end_to_end(api_client, otp_outbox):
    user = verified_user()
    token = post(api_client, "login", {"phone_number": PHONE}).json()["data"]["token"]
    response = sign_in(api_client, token, otp_outbox[-1].code)
    assert response.status_code == 200
    assert int(AccessToken(response.json()["data"]["tokens"]["access"])["user_id"]) == user.pk


def test_an_otp_can_only_be_used_once(api_client, otp_outbox):
    token, code = register_and_get_code(api_client, otp_outbox)
    assert sign_in(api_client, token, code).status_code == 200
    again = sign_in(api_client, token, code)
    assert again.status_code == 400
    assert "Invalid or expired token" in again.json()["error"]


def test_wrong_otp_counts_attempts_and_locks_the_token(api_client, otp_outbox, settings):
    settings.OTP_MAX_ATTEMPTS = 3
    token, code = register_and_get_code(api_client, otp_outbox)
    wrong = different_code(code)

    first = sign_in(api_client, token, wrong)
    assert first.status_code == 400  # a wrong code is a 400, never a 401 (401 makes the frontend log out)
    assert first.json()["errors"] == ["Invalid OTP. 2 attempts left."]
    assert sign_in(api_client, token, wrong).json()["errors"] == ["Invalid OTP. 1 attempt left."]
    last = sign_in(api_client, token, wrong)
    assert last.json()["errors"] == ["Invalid OTP. Please request a new one."]
    assert OTPRequest.objects.get().attempts == 3  # the counter survived the error response

    locked = sign_in(api_client, token, code)  # even the right code is refused now
    assert locked.status_code == 400
    assert "Too many incorrect attempts" in locked.json()["error"]
    assert not User.objects.get().is_phone_verified


def test_expired_otp(api_client, otp_outbox):
    token, code = register_and_get_code(api_client, otp_outbox)
    OTPRequest.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    response = sign_in(api_client, token, code)
    assert response.status_code == 400
    assert "expired" in response.json()["error"]


@pytest.mark.parametrize("bad", ["12345", "1234567", "abcdef", "12 456", ""])
def test_otp_must_be_six_digits_and_a_malformed_one_is_not_counted_as_a_guess(
    api_client, otp_outbox, bad
):
    token, _ = register_and_get_code(api_client, otp_outbox)
    response = sign_in(api_client, token, bad)
    assert response.status_code == 400
    assert "otp" in response.json()["field_errors"]
    assert OTPRequest.objects.get().attempts == 0


def test_unknown_token(api_client):
    response = sign_in(api_client, "does-not-exist", "123456")
    assert response.status_code == 400
    assert "Invalid or expired token" in response.json()["error"]


def test_a_profile_otp_cannot_be_used_to_sign_in(api_client, otp_outbox):
    user = verified_user()
    token = start_otp(user=user, purpose=OTPRequest.Purpose.PROFILE_PHONE, target="+8801799999999")
    response = sign_in(api_client, token, otp_outbox[-1].code)
    assert response.status_code == 400
    assert OTPRequest.objects.get().consumed_at is None


def test_a_disabled_account_cannot_finish_signing_in(api_client, otp_outbox):
    token, code = register_and_get_code(api_client, otp_outbox)
    User.objects.update(is_active=False)
    response = sign_in(api_client, token, code)
    assert response.status_code == 400
    assert response.json()["errors"] == ["This account is disabled."]


# --- guest cart / favorites ---------------------------------------------------------------------------
@pytest.fixture
def received():
    calls = []

    def receiver(sender, **kwargs):
        calls.append(kwargs)

    guest_data_received.connect(receiver, weak=False)
    yield calls
    guest_data_received.disconnect(receiver)


def test_guest_cart_and_favorites_are_handed_to_receivers(api_client, otp_outbox, received):
    token, code = register_and_get_code(api_client, otp_outbox)
    cart = [{"product_id": 1, "quantity": 2, "variant_id": 5}, {"product_id": 2, "quantity": 1}]
    favorites = [{"product_id": 7}]

    response = sign_in(api_client, token, code, cart=cart, favorite=favorites)

    assert response.status_code == 200
    assert len(received) == 1
    assert received[0]["user"].phone_number == PHONE
    assert received[0]["cart"] == cart and received[0]["favorites"] == favorites


def test_no_signal_when_the_guest_had_nothing(api_client, otp_outbox, received):
    token, code = register_and_get_code(api_client, otp_outbox)
    assert sign_in(api_client, token, code, cart=[], favorite=[]).status_code == 200
    assert received == []


def test_a_broken_receiver_never_blocks_sign_in(api_client, otp_outbox, caplog):
    def exploding(sender, **kwargs):
        raise RuntimeError("cart app bug")

    guest_data_received.connect(exploding, weak=False)
    try:
        token, code = register_and_get_code(api_client, otp_outbox)
        response = sign_in(api_client, token, code, cart=[{"product_id": 1, "quantity": 1}])
    finally:
        guest_data_received.disconnect(exploding)

    assert response.status_code == 200 and response.json()["data"]["tokens"]["access"]
    assert "guest_data_received receiver" in caplog.text


@pytest.mark.parametrize(
    "payload",
    [{"cart": ["not-a-dict"]}, {"favorite": "nope"}, {"cart": [{"product_id": 1}] * 101}],
)
def test_malformed_guest_lists_are_rejected_before_the_otp_is_used(api_client, otp_outbox, payload):
    token, code = register_and_get_code(api_client, otp_outbox)
    assert sign_in(api_client, token, code, **payload).status_code == 400
    assert OTPRequest.objects.get().consumed_at is None  # user can retry


# --- resend-otp ---------------------------------------------------------------------------------------
def test_resend_is_blocked_during_the_cooldown(api_client, otp_outbox):
    token, _ = register_and_get_code(api_client, otp_outbox)
    response = post(api_client, "resend-otp", {"token": token})
    assert response.status_code == 429
    assert 1 <= int(response["Retry-After"]) <= 60
    assert len(otp_outbox) == 1


def test_resend_issues_a_new_code_and_resets_attempts(api_client, otp_outbox):
    token, first_code = register_and_get_code(api_client, otp_outbox)
    OTPRequest.objects.update(attempts=4)
    expire_cooldown()

    response = post(api_client, "resend-otp", {"token": token})

    assert response.status_code == 200 and response.json()["success"] is True
    assert response.json()["message"]  # the frontend shows it
    otp = OTPRequest.objects.get()
    assert (otp.attempts, otp.resend_count) == (0, 1) and len(otp_outbox) == 2
    new_code = otp_outbox[-1].code
    if new_code != first_code:  # the previous code is dead
        assert sign_in(api_client, token, first_code).status_code == 400
    assert sign_in(api_client, token, new_code).status_code == 200


def test_an_expired_otp_can_be_resent(api_client, otp_outbox):
    token, _ = register_and_get_code(api_client, otp_outbox)
    OTPRequest.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
    expire_cooldown()
    assert post(api_client, "resend-otp", {"token": token}).status_code == 200
    assert sign_in(api_client, token, otp_outbox[-1].code).status_code == 200


def test_resend_has_a_maximum(api_client, otp_outbox, settings):
    token, _ = register_and_get_code(api_client, otp_outbox)
    OTPRequest.objects.update(resend_count=settings.OTP_MAX_RESENDS)
    expire_cooldown()
    response = post(api_client, "resend-otp", {"token": token})
    assert response.status_code == 400
    assert "Too many resend" in response.json()["error"]


def test_resend_with_an_unknown_or_used_token(api_client, otp_outbox):
    assert post(api_client, "resend-otp", {"token": "nope"}).status_code == 400
    token, code = register_and_get_code(api_client, otp_outbox)
    sign_in(api_client, token, code)
    assert post(api_client, "resend-otp", {"token": token}).status_code == 400
