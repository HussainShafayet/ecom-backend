"""The numbers a client must not keep its own copy of: how long before another code, how long a code works, how many digits.
The storefront once waited 30 s before "Resend" while the setting was 60 and was throttled; now it reads them from the answer."""
import pytest
from django.conf import settings
from django.test import override_settings

from .helpers import PHONE, authed_client, expire_cooldown, post, register_and_get_code, sign_up, verified_user

pytestmark = pytest.mark.django_db

TIMING = {"resend_after", "expires_in", "length"}


def test_registering_says_the_otp_timing_with_the_token(api_client, otp_outbox):
    data = sign_up(api_client).json()["data"]
    assert set(data) == {"token", *TIMING}
    assert data["resend_after"] == settings.OTP_RESEND_COOLDOWN_SECONDS
    assert data["expires_in"] == settings.OTP_TTL_SECONDS
    assert data["length"] == settings.OTP_LENGTH


def test_logging_in_says_it_too(api_client, otp_outbox):
    verified_user()
    data = post(api_client, "login", {"phone_number": PHONE}).json()["data"]
    assert set(data) == {"token", *TIMING}


def test_resending_says_the_timing_again(api_client, otp_outbox):
    token, _ = register_and_get_code(api_client, otp_outbox)
    expire_cooldown()
    response = post(api_client, "resend-otp", {"token": token})
    assert response.status_code == 200
    assert response.json()["data"] == {
        "resend_after": settings.OTP_RESEND_COOLDOWN_SECONDS, "expires_in": settings.OTP_TTL_SECONDS, "length": settings.OTP_LENGTH,
    }


def test_asking_for_a_code_for_a_new_profile_number_says_it_too(otp_outbox):
    user = verified_user()
    response = authed_client(user).post("/api/v1/accounts/request-otp/", {"phone_number": "+8801812345678"})
    assert response.status_code == 200, response.content
    assert set(response.json()["data"]) == {"token", *TIMING}


@override_settings(OTP_RESEND_COOLDOWN_SECONDS=45, OTP_TTL_SECONDS=120, OTP_LENGTH=6)
def test_the_answer_follows_the_settings_not_a_constant(api_client, otp_outbox):
    data = sign_up(api_client).json()["data"]
    assert (data["resend_after"], data["expires_in"]) == (45, 120)


def test_a_resend_inside_the_cooldown_says_how_long_to_wait_in_the_header_and_in_words(api_client, otp_outbox):
    token, _ = register_and_get_code(api_client, otp_outbox)
    response = post(api_client, "resend-otp", {"token": token})
    assert response.status_code == 429
    wait = int(response["Retry-After"])
    assert 1 <= wait <= settings.OTP_RESEND_COOLDOWN_SECONDS
    # the sentence the storefront falls back to when the browser cannot read the header
    assert f"Expected available in {wait} second" in " ".join(response.json()["errors"])


def test_browsers_may_read_retry_after():
    assert "Retry-After" in settings.CORS_EXPOSE_HEADERS


@override_settings(CORS_ALLOWED_ORIGINS=["http://localhost:3000"])
def test_a_page_on_the_storefront_origin_is_told_it_may_read_retry_after(api_client, otp_outbox):
    token, _ = register_and_get_code(api_client, otp_outbox)
    response = post(api_client, "resend-otp", {"token": token}, HTTP_ORIGIN="http://localhost:3000")
    assert response.status_code == 429
    assert "Retry-After" in response["Access-Control-Expose-Headers"]
