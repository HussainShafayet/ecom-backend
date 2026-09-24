"""How a one-time code reaches the user. Pick one with the OTP_BACKEND setting (dotted path).

To add a real SMS/email provider: subclass OTPBackend, implement `send`, and point OTP_BACKEND at it.
`target` is a phone number (+880...) or an email address; `purpose` is an OTPRequest.Purpose value.
Raise any exception on delivery failure: the caller rolls the OTP back and answers 503.

Codes never reach an API response, with one exception: a backend that sets `reveals_code = True`
(only `BrowserOTPBackend`, DEBUG only). The OTP service then hands the code back to the view.
"""
import logging
from dataclasses import dataclass
from typing import ClassVar

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

logger = logging.getLogger("apps.accounts.otp")


class OTPBackend:
    # True ONLY for dev backends that also show the code in the API response (see BrowserOTPBackend).
    reveals_code: ClassVar[bool] = False

    def send(self, *, target, code, purpose):
        raise NotImplementedError


class ConsoleOTPBackend(OTPBackend):
    """DEV ONLY: prints the code in the server log so you can type it into the frontend."""

    def send(self, *, target, code, purpose):
        logger.warning("[DEV ONLY] OTP for %s (%s): %s", target, purpose, code)


class BrowserOTPBackend(ConsoleOTPBackend):
    """DEV ONLY: logs the code like the console backend AND puts it in the `message` of the response, which
    the React app already shows ("OTP sent to +88017****5678. [DEV] Your code is 123456."). Refuses to run
    unless DEBUG is on, and the prod settings reject it, so a code can never reach a production response.
    """

    reveals_code = True

    def __init__(self):
        self._require_debug()

    def send(self, *, target, code, purpose):
        self._require_debug()
        super().send(target=target, code=code, purpose=purpose)

    @staticmethod
    def _require_debug():
        if not settings.DEBUG:
            raise ImproperlyConfigured(
                "BrowserOTPBackend shows OTP codes in API responses, so it only works when DEBUG is True. "
                "Set OTP_BACKEND to a real delivery class (or ConsoleOTPBackend) outside development."
            )


@dataclass(frozen=True)
class SentOTP:
    target: str
    code: str
    purpose: str


class LocMemOTPBackend(OTPBackend):
    """Keeps sent codes in `outbox` (like Django's locmem email backend); used by the tests."""

    outbox: ClassVar[list] = []

    def send(self, *, target, code, purpose):
        self.outbox.append(SentOTP(target=target, code=code, purpose=purpose))


def get_otp_backend():
    return import_string(settings.OTP_BACKEND)()
