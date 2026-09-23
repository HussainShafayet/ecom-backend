import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.otp.backends import LocMemOTPBackend


@pytest.fixture(autouse=True)
def _isolated_environment(settings):
    """Every test: codes go to an in-memory outbox (never the console) and throttle counters start empty."""
    settings.OTP_BACKEND = "apps.accounts.otp.backends.LocMemOTPBackend"
    LocMemOTPBackend.outbox.clear()
    cache.clear()
    yield
    LocMemOTPBackend.outbox.clear()
    cache.clear()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def otp_outbox():
    """The list of SentOTP(target, code, purpose) 'delivered' so far in this test."""
    return LocMemOTPBackend.outbox
