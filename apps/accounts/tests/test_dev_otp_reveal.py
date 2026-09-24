"""BrowserOTPBackend (DEV ONLY): the OTP shown in the API `message`, and every guard that keeps it out of production.

The safety claims, each with a test below:
  - only the reveal backend puts a code in a response, and only in the four "OTP sent" messages;
  - it refuses to work when DEBUG is off (the backend itself, the service, and the API answer);
  - prod settings refuse to load with it; the default backend is still the console one;
  - Console and LocMem responses are byte-for-byte what they were before (exact messages, no code);
  - the code is never stored.
"""
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from django.core.exceptions import ImproperlyConfigured

from apps.accounts.models import OTPRequest, User
from apps.accounts.otp import service as otp_service
from apps.accounts.otp.backends import (
    BrowserOTPBackend,
    ConsoleOTPBackend,
    LocMemOTPBackend,
    OTPBackend,
    get_otp_backend,
)

from .helpers import PHONE, authed_client, expire_cooldown, post, sign_in, sign_up, verified_user

pytestmark = pytest.mark.django_db

BROWSER = "apps.accounts.otp.backends.BrowserOTPBackend"
CONSOLE = "apps.accounts.otp.backends.ConsoleOTPBackend"
LOCMEM = "apps.accounts.otp.backends.LocMemOTPBackend"
CODE = "482915"
BACKEND_DIR = Path(__file__).resolve().parents[3]

LOGIN_PHONE, NEW_PHONE, NEW_EMAIL = "+8801811111111", "+8801799999999", "new@example.com"
PROFILE_OTP_URL = "/api/v1/accounts/request-otp/"
VERIFY_PROFILE_URL = "/api/v1/accounts/verify-otp-for-profile/"
# The messages of the four endpoints that send a code, exactly as they were before the reveal backend existed.
BASE_MESSAGES = {
    "register": "OTP sent to +88017****5678.",
    "resend": "A new OTP has been sent.",
    "login": "OTP sent to +88018****1111.",
    "profile_phone": "OTP sent to +88017****9999.",
    "profile_email": "OTP sent to n***@example.com.",
}


class ClaimsToRevealBackend(OTPBackend):
    """A backend that reveals codes but has no DEBUG check of its own (the service must still refuse)."""

    reveals_code = True

    def send(self, *, target, code, purpose):
        pass


class TruthyButNotTrueBackend(ClaimsToRevealBackend):
    reveals_code = "yes"  # like a mock's auto-attribute: truthy, but not the real flag


# --- helpers ------------------------------------------------------------------------------------------
def hint(message, code=CODE):
    return f"{message} [DEV] Your code is {code}."


def run_flows(api_client):
    """Every endpoint that sends a code: register, resend, login, profile phone and profile email."""
    register = sign_up(api_client)  # PHONE, not verified yet
    expire_cooldown()
    resend = post(api_client, "resend-otp", {"token": register.json()["data"]["token"]})
    member = verified_user(LOGIN_PHONE)
    login = post(api_client, "login", {"phone_number": LOGIN_PHONE})
    profile = authed_client(member)
    return {
        "register": register,
        "resend": resend,
        "login": login,
        "profile_phone": profile.post(PROFILE_OTP_URL, {"phone_number": NEW_PHONE}),
        "profile_email": profile.post(PROFILE_OTP_URL, {"email": NEW_EMAIL}),
    }


def code_from(response):
    match = re.search(r"\[DEV\] Your code is (\d{6})\.$", response.json()["message"])
    assert match, response.json()["message"]
    return match.group(1)


def assert_no_code_anywhere(response, code=CODE):
    body = response.content.decode()
    assert code not in body and "[DEV]" not in body


@pytest.fixture
def dev_mode(settings):
    """A developer's machine: the reveal backend selected and DEBUG on (pytest itself forces DEBUG off)."""
    settings.OTP_BACKEND = BROWSER
    settings.DEBUG = True


@pytest.fixture
def reveal(dev_mode, monkeypatch):
    """dev_mode plus a known code, so messages can be compared exactly."""
    monkeypatch.setattr(otp_service, "_generate_code", lambda: CODE)


# --- the reveal: four endpoints -----------------------------------------------------------------------
def test_the_reveal_backend_adds_the_code_to_the_message_of_all_four_endpoints(api_client, reveal, caplog):
    with caplog.at_level(logging.WARNING, logger="apps.accounts.otp"):
        responses = run_flows(api_client)

    assert list(responses) == list(BASE_MESSAGES)
    for name, response in responses.items():
        assert response.status_code == 200, (name, response.content)
        assert response.json()["message"] == hint(BASE_MESSAGES[name]), name
        # the code sits in `message` only: not in `data`, not anywhere else in the body
        assert response.content.decode().count(CODE) == 1, name
    assert set(responses["register"].json()["data"]) == {"token"}
    assert responses["resend"].json()["data"] is None
    # it still logs like the console backend
    assert f"[DEV ONLY] OTP for {PHONE} (register): {CODE}" in caplog.text


def test_the_revealed_code_really_signs_you_in(api_client, dev_mode):
    token = sign_up(api_client).json()["data"]["token"]
    expire_cooldown()
    resent = post(api_client, "resend-otp", {"token": token})
    signed_in = sign_in(api_client, token, code_from(resent))
    assert signed_in.status_code == 200 and signed_in.json()["data"]["tokens"]["access"]

    login = post(api_client, "login", {"phone_number": PHONE})
    assert sign_in(api_client, login.json()["data"]["token"], code_from(login)).status_code == 200


def test_the_revealed_code_really_verifies_a_profile_change(dev_mode):
    client = authed_client(verified_user())
    requested = client.post(PROFILE_OTP_URL, {"email": NEW_EMAIL})
    verified = client.post(
        VERIFY_PROFILE_URL, {"token": requested.json()["data"]["token"], "otp": code_from(requested)}
    )
    assert verified.status_code == 200
    assert verified.json()["data"] == {"field": "email", "value": NEW_EMAIL}


def test_every_other_message_stays_the_same_while_the_reveal_backend_is_active(api_client, reveal):
    token = sign_up(api_client).json()["data"]["token"]

    cooldown = post(api_client, "resend-otp", {"token": token})
    unknown = post(api_client, "login", {"phone_number": "+8801700000000"})
    wrong = sign_in(api_client, token, "000000")
    right = sign_in(api_client, token, CODE)
    for response in (cooldown, unknown, wrong):
        assert response.status_code in (400, 429)
        assert response.json()["success"] is False
        assert_no_code_anywhere(response)
    assert wrong.json()["errors"] == ["Invalid OTP. 4 attempts left."]
    assert right.status_code == 200 and right.json()["message"] == "Signed in successfully."
    assert "[DEV]" not in right.content.decode()

    client = authed_client(User.objects.get(phone_number=PHONE))
    requested = client.post(PROFILE_OTP_URL, {"email": NEW_EMAIL})
    verified = client.post(
        VERIFY_PROFILE_URL, {"token": requested.json()["data"]["token"], "otp": CODE}
    )
    assert verified.json()["message"] == "Verified. Save your profile to apply the change."
    assert_no_code_anywhere(verified)
    saved = client.put("/api/v1/accounts/profile/", {"email": NEW_EMAIL})
    assert saved.json()["message"] == "Profile updated."
    assert_no_code_anywhere(saved)


def test_the_revealed_code_is_never_stored(api_client, reveal, monkeypatch):
    marker = "zz-482915-zz"  # cannot occur by chance inside a hex hash, a phone number or a timestamp
    monkeypatch.setattr(otp_service, "_generate_code", lambda: marker)

    registered = sign_up(api_client)
    expire_cooldown()
    resent = post(api_client, "resend-otp", {"token": registered.json()["data"]["token"]})
    assert marker in registered.json()["message"] and marker in resent.json()["message"]  # not vacuous

    token = registered.json()["data"]["token"]
    otp = OTPRequest.objects.get()
    assert otp.code_hash == otp_service._hash_code(token, marker) and otp.code_hash != marker
    stored = str(list(OTPRequest.objects.values()) + list(User.objects.values()))
    assert marker not in stored


# --- the other backends: exactly the old behaviour ----------------------------------------------------
@pytest.mark.parametrize("backend", [CONSOLE, LOCMEM])
def test_console_and_locmem_keep_the_exact_old_messages_and_never_show_a_code(
    api_client, settings, monkeypatch, caplog, otp_outbox, backend
):
    settings.OTP_BACKEND = backend
    settings.DEBUG = True  # the worst case for them: a dev machine with DEBUG on
    monkeypatch.setattr(otp_service, "_generate_code", lambda: CODE)

    with caplog.at_level(logging.WARNING, logger="apps.accounts.otp"):
        responses = run_flows(api_client)

    for name, response in responses.items():
        assert response.status_code == 200, (name, response.content)
        assert response.json()["message"] == BASE_MESSAGES[name], name
        assert_no_code_anywhere(response)
    # ...although a code really was delivered five times (so the checks above are not vacuous)
    if backend == CONSOLE:
        assert caplog.text.count(CODE) == 5
    else:
        assert [sent.code for sent in otp_outbox] == [CODE] * 5


def test_only_the_reveal_backend_declares_reveals_code():
    assert BrowserOTPBackend.reveals_code is True
    assert (OTPBackend.reveals_code, ConsoleOTPBackend.reveals_code, LocMemOTPBackend.reveals_code) == (
        False,
        False,
        False,
    )


def test_a_repr_of_the_result_never_contains_the_code():
    assert CODE not in repr(otp_service.IssuedOTP(token="t", dev_code=CODE))


# --- DEBUG off: it refuses ----------------------------------------------------------------------------
def test_the_backend_refuses_to_be_created_without_debug(settings):
    settings.DEBUG = False
    with pytest.raises(ImproperlyConfigured, match="only works when DEBUG is True"):
        BrowserOTPBackend()
    settings.OTP_BACKEND = BROWSER
    with pytest.raises(ImproperlyConfigured, match="only works when DEBUG is True"):
        get_otp_backend()


def test_the_backend_works_with_debug_on(settings):
    settings.DEBUG = True
    assert isinstance(BrowserOTPBackend(), BrowserOTPBackend)
    settings.OTP_BACKEND = BROWSER
    assert isinstance(get_otp_backend(), BrowserOTPBackend)


def test_the_backend_checks_debug_again_when_sending(settings, caplog):
    settings.DEBUG = True
    backend = BrowserOTPBackend()
    settings.DEBUG = False
    with caplog.at_level(logging.DEBUG), pytest.raises(ImproperlyConfigured):
        backend.send(target=PHONE, code=CODE, purpose="register")
    assert CODE not in caplog.text  # refused before anything was logged


@pytest.mark.parametrize("flow", ["register", "login", "resend", "profile"])
def test_with_debug_off_all_four_endpoints_answer_503_and_leak_nothing(
    api_client, settings, monkeypatch, caplog, flow
):
    member = verified_user(LOGIN_PHONE)
    pending = otp_service.start_otp(user=member, purpose=OTPRequest.Purpose.REGISTER, target=LOGIN_PHONE)
    expire_cooldown()
    settings.OTP_BACKEND = BROWSER
    settings.DEBUG = False  # e.g. a deployment that copied the dev .env
    monkeypatch.setattr(otp_service, "_generate_code", lambda: CODE)
    otps_before, users_before = list(OTPRequest.objects.values()), User.objects.count()

    requests = {
        "register": lambda: sign_up(api_client),
        "login": lambda: post(api_client, "login", {"phone_number": LOGIN_PHONE}),
        "resend": lambda: post(api_client, "resend-otp", {"token": pending.token}),
        "profile": lambda: authed_client(member).post(PROFILE_OTP_URL, {"email": NEW_EMAIL}),
    }
    with caplog.at_level(logging.DEBUG):
        response = requests[flow]()

    assert response.status_code == 503 and response.json()["success"] is False
    assert_no_code_anywhere(response)
    assert CODE not in caplog.text
    assert "only works when DEBUG is True" in caplog.text  # the developer can see why in the server log
    assert list(OTPRequest.objects.values()) == otps_before and User.objects.count() == users_before


def test_the_service_never_reveals_without_debug_even_if_a_backend_claims_to(api_client, settings, monkeypatch):
    settings.OTP_BACKEND = f"{ClaimsToRevealBackend.__module__}.ClaimsToRevealBackend"
    settings.DEBUG = False
    monkeypatch.setattr(otp_service, "_generate_code", lambda: CODE)
    response = sign_up(api_client)
    assert response.status_code == 200
    assert response.json()["message"] == BASE_MESSAGES["register"]
    assert_no_code_anywhere(response)


def test_the_service_reveals_only_when_the_flag_is_exactly_true(api_client, settings, monkeypatch):
    settings.DEBUG = True
    monkeypatch.setattr(otp_service, "_generate_code", lambda: CODE)

    settings.OTP_BACKEND = f"{ClaimsToRevealBackend.__module__}.ClaimsToRevealBackend"
    assert sign_up(api_client).json()["message"] == hint(BASE_MESSAGES["register"])  # control: the flag drives it

    settings.OTP_BACKEND = f"{TruthyButNotTrueBackend.__module__}.TruthyButNotTrueBackend"
    response = sign_up(api_client, phone="+8801722222222")
    assert response.json()["message"] == "OTP sent to +88017****2222."
    assert_no_code_anywhere(response)


# --- production and defaults (settings modules are loaded in a clean interpreter) ---------------------
def load_settings(module, **env):
    """Import a settings module in a fresh python and print its OTP_BACKEND and DEBUG as JSON.

    The developer's `.env` is skipped on purpose, so what these tests see never depends on the local file.
    """
    script = (
        "import environ, importlib, json, sys\n"
        "environ.Env.read_env = classmethod(lambda cls, *args, **kwargs: None)\n"
        "settings = importlib.import_module(sys.argv[1])\n"
        "print(json.dumps({'OTP_BACKEND': settings.OTP_BACKEND, 'DEBUG': settings.DEBUG}))\n"
    )
    clean = {k: v for k, v in os.environ.items() if k not in ("OTP_BACKEND", "DEBUG")}
    clean.update(SECRET_KEY="x" * 50, DATABASE_URL="postgres://user:pass@127.0.0.1:5432/never_connected", **env)
    return subprocess.run(
        [sys.executable, "-c", script, module],
        cwd=BACKEND_DIR, env=clean, capture_output=True, text=True, timeout=60, check=False,
    )


@pytest.mark.parametrize("module", ["config.settings.base", "config.settings.dev"])
def test_the_default_backend_is_still_the_console_one(module):
    result = load_settings(module)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[-1])["OTP_BACKEND"] == CONSOLE


@pytest.mark.parametrize("path", [BROWSER, "somewhere.else.BrowserOTPBackend"])
def test_production_settings_refuse_the_reveal_backend(path):
    result = load_settings("config.settings.prod", OTP_BACKEND=path)
    assert result.returncode != 0
    assert "ImproperlyConfigured" in result.stderr and "BrowserOTPBackend" in result.stderr
    assert "not allowed in production" in result.stderr


def test_production_settings_still_load_with_a_real_backend_and_ignore_a_debug_variable():
    result = load_settings("config.settings.prod", OTP_BACKEND="myshop.sms.RealProviderBackend", DEBUG="True")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[-1]) == {
        "OTP_BACKEND": "myshop.sms.RealProviderBackend",
        "DEBUG": False,
    }


def test_production_settings_still_have_no_default_backend():
    result = load_settings("config.settings.prod")
    assert result.returncode != 0 and "OTP_BACKEND" in result.stderr
