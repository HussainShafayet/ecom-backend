"""OTP lifecycle: start, resend, verify. All rules (expiry, attempts, cooldowns) live here."""
import hashlib
import hmac
import logging
import math
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import Throttled, ValidationError

from apps.core.exceptions import ServiceUnavailable

from ..models import OTPRequest
from .backends import get_otp_backend

logger = logging.getLogger(__name__)

MSG_INVALID_TOKEN = "Invalid or expired token. Please request a new OTP."


def _hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _hash_code(token, code):
    # Keyed and bound to the token, so a leaked hash is useless without SECRET_KEY.
    return hmac.new(settings.SECRET_KEY.encode(), f"{token}:{code}".encode(), hashlib.sha256).hexdigest()


def _generate_code():
    return f"{secrets.randbelow(10 ** settings.OTP_LENGTH):0{settings.OTP_LENGTH}d}"


def _deliver(otp, code):
    try:
        get_otp_backend().send(target=otp.target, code=code, purpose=otp.purpose)
    except Exception as exc:  # any provider failure: roll back, tell the caller to retry
        logger.error("OTP delivery failed for purpose=%s", otp.purpose, exc_info=exc)
        raise ServiceUnavailable("We could not send the OTP right now. Please try again shortly.") from exc


def start_otp(*, user, purpose, target):
    """Create and send a new OTP for `target`. Returns the opaque token the client keeps."""
    now = timezone.now()
    recent = list(
        OTPRequest.objects.filter(target=target, created_at__gte=now - timedelta(hours=1))
        .order_by("created_at")
        .values_list("created_at", flat=True)
    )
    if len(recent) >= settings.OTP_MAX_REQUESTS_PER_TARGET_PER_HOUR:
        wait = math.ceil((recent[0] + timedelta(hours=1) - now).total_seconds())
        raise Throttled(wait=max(wait, 1))

    token, code = secrets.token_urlsafe(32), _generate_code()
    with transaction.atomic():
        # Only the newest code for a target/purpose is valid.
        OTPRequest.objects.filter(target=target, purpose=purpose, consumed_at__isnull=True).update(
            consumed_at=now
        )
        otp = OTPRequest.objects.create(
            token_hash=_hash_token(token),
            purpose=purpose,
            target=target,
            user=user,
            code_hash=_hash_code(token, code),
            last_sent_at=now,
            expires_at=now + timedelta(seconds=settings.OTP_TTL_SECONDS),
        )
        _deliver(otp, code)
    return token


def resend_otp(*, token, purposes):
    """Send a fresh code for an existing token (also allowed after the old one expired)."""
    now = timezone.now()
    with transaction.atomic():
        otp = (
            OTPRequest.objects.select_for_update()
            .filter(token_hash=_hash_token(token), purpose__in=purposes, consumed_at__isnull=True)
            .first()
        )
        if otp is None:
            raise ValidationError(MSG_INVALID_TOKEN)
        wait = math.ceil(
            (otp.last_sent_at + timedelta(seconds=settings.OTP_RESEND_COOLDOWN_SECONDS) - now).total_seconds()
        )
        if wait > 0:
            raise Throttled(wait=wait)
        if otp.resend_count >= settings.OTP_MAX_RESENDS:
            raise ValidationError("Too many resend requests. Please start again.")

        code = _generate_code()
        otp.code_hash = _hash_code(token, code)
        otp.attempts = 0
        otp.resend_count += 1
        otp.last_sent_at = now
        otp.expires_at = now + timedelta(seconds=settings.OTP_TTL_SECONDS)
        otp.save(update_fields=["code_hash", "attempts", "resend_count", "last_sent_at", "expires_at"])
        _deliver(otp, code)
    return otp


def verify_otp(*, token, code, purposes, user=None):
    """Check `code` for `token`; on success mark it used and return the OTPRequest.

    Only OTPs whose purpose is in `purposes` count, so a profile-change OTP can never log someone in.
    Pass `user` for authenticated flows (profile changes): a token issued to someone else is then
    "invalid". A wrong guess is recorded before the error is raised (raising inside the atomic block
    would roll the attempt counter back).
    """
    now = timezone.now()
    failure = None
    with transaction.atomic():
        candidates = OTPRequest.objects.select_for_update().select_related("user")
        if user is not None:
            candidates = candidates.filter(user=user)
        otp = candidates.filter(token_hash=_hash_token(token), purpose__in=purposes).first()
        if otp is None or otp.consumed_at is not None:
            failure = MSG_INVALID_TOKEN
        elif otp.expires_at <= now:
            failure = "This OTP has expired. Please request a new one."
        elif otp.attempts >= settings.OTP_MAX_ATTEMPTS:
            failure = "Too many incorrect attempts. Please request a new OTP."
        elif hmac.compare_digest(_hash_code(token, code), otp.code_hash):
            otp.consumed_at = now
            otp.save(update_fields=["consumed_at"])
            return otp
        else:
            otp.attempts += 1
            otp.save(update_fields=["attempts"])
            left = settings.OTP_MAX_ATTEMPTS - otp.attempts
            failure = f"Invalid OTP. {left} attempt{'s' if left != 1 else ''} left." if left else (
                "Invalid OTP. Please request a new one."
            )
    raise ValidationError(failure)
