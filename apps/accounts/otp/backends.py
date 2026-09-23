"""How a one-time code reaches the user. Pick one with the OTP_BACKEND setting (dotted path).

To add a real SMS/email provider: subclass OTPBackend, implement `send`, and point OTP_BACKEND at it.
`target` is a phone number (+880...) or an email address; `purpose` is an OTPRequest.Purpose value.
Raise any exception on delivery failure: the caller rolls the OTP back and answers 503.
"""
import logging
from dataclasses import dataclass
from typing import ClassVar

from django.conf import settings
from django.utils.module_loading import import_string

logger = logging.getLogger("apps.accounts.otp")


class OTPBackend:
    def send(self, *, target, code, purpose):
        raise NotImplementedError


class ConsoleOTPBackend(OTPBackend):
    """DEV ONLY: prints the code in the server log so you can type it into the frontend."""

    def send(self, *, target, code, purpose):
        logger.warning("[DEV ONLY] OTP for %s (%s): %s", target, purpose, code)


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
