import sentry_sdk
from django.conf import settings


def test_sentry_is_off_without_a_dsn():
    """Tests, CI and local dev must never report to a real Sentry project."""
    assert settings.SENTRY_DSN == ""
    assert not sentry_sdk.get_client().is_active()
