"""Sign-up / sign-in flows built on the OTP service. Views stay thin and call these."""
import logging

from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError, transaction
from rest_framework.exceptions import ValidationError
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from .models import OTPRequest
from .otp import service as otp_service
from .signals import guest_data_received

logger = logging.getLogger(__name__)
User = get_user_model()

AUTH_PURPOSES = (OTPRequest.Purpose.REGISTER, OTPRequest.Purpose.LOGIN)
PHONE_EXISTS = "A user with this phone number already exists."
EMAIL_EXISTS = "A user with this email already exists."
ACCOUNT_DISABLED = "This account is disabled."


def register_user(*, name, phone_number, email=None):
    """Create (or re-use, if never verified) the user and send a register OTP. Returns (user, IssuedOTP)."""
    email = email.strip().lower() if email else None
    try:
        with transaction.atomic():
            user = User.objects.select_for_update().filter(phone_number=phone_number).first()
            if user is not None and user.is_phone_verified:
                raise ValidationError({"phone_number": [PHONE_EXISTS]})
            if user is not None and not user.is_active:
                raise ValidationError(ACCOUNT_DISABLED)
            if email and User.objects.filter(email__iexact=email).exclude(pk=getattr(user, "pk", None)).exists():
                raise ValidationError({"email": [EMAIL_EXISTS]})

            if user is None:
                user = User.objects.create_user(phone_number, name=name, email=email)
            else:  # someone who started signing up earlier but never entered the code
                user.name, user.email = name, email
                user.save(update_fields=["name", "email", "updated_at"])

            issued = otp_service.start_otp(
                user=user, purpose=OTPRequest.Purpose.REGISTER, target=phone_number
            )
    except IntegrityError as exc:  # two simultaneous sign-ups for the same number
        raise ValidationError({"phone_number": [PHONE_EXISTS]}) from exc
    return user, issued


def start_login(*, phone_number):
    """Send a login OTP to an existing, verified user. Returns (user, IssuedOTP)."""
    user = User.objects.filter(phone_number=phone_number).first()
    if user is None:
        raise ValidationError(
            {"phone_number": ["No account found with this phone number. Please sign up first."]}
        )
    if not user.is_active:
        raise ValidationError(ACCOUNT_DISABLED)
    if not user.is_phone_verified:
        raise ValidationError(
            {"phone_number": ["This number has not been verified yet. Please sign up again to verify it."]}
        )
    issued = otp_service.start_otp(user=user, purpose=OTPRequest.Purpose.LOGIN, target=phone_number)
    return user, issued


def resend_auth_otp(*, token):
    return otp_service.resend_otp(token=token, purposes=AUTH_PURPOSES)


def issue_tokens(user):
    refresh = RefreshToken.for_user(user)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


def complete_sign_in(*, token, code, cart=None, favorites=None):
    """Verify the OTP, mark the phone verified and return {"access", "refresh"}."""
    otp = otp_service.verify_otp(token=token, code=code, purposes=AUTH_PURPOSES)
    user = otp.user
    if not user.is_active:
        raise ValidationError(ACCOUNT_DISABLED)
    if not user.is_phone_verified:
        user.is_phone_verified = True
        user.save(update_fields=["is_phone_verified", "updated_at"])

    if cart or favorites:
        for receiver, result in guest_data_received.send_robust(
            sender=User, user=user, cart=cart or [], favorites=favorites or []
        ):
            if isinstance(result, Exception):  # never let a cart/wishlist bug block a sign-in
                logger.error("guest_data_received receiver %r failed", receiver, exc_info=result)
    return issue_tokens(user)


def rotate_refresh_token(*, refresh):
    """Exchange a refresh token for a new access + refresh pair (the old refresh is blacklisted).

    simplejwt raises DoesNotExist (-> 500) if the token's user was deleted; that is a 401 here.
    """
    serializer = TokenRefreshSerializer(data={"refresh": refresh})
    try:
        serializer.is_valid(raise_exception=True)
    except TokenError as exc:
        raise InvalidToken(exc.args[0]) from exc
    except ObjectDoesNotExist as exc:
        raise InvalidToken("Token is invalid or expired") from exc
    return serializer.validated_data


def blacklist_refresh_token(refresh):
    """Log out: revoke the refresh token. Idempotent; an already invalid token is not an error."""
    try:
        RefreshToken(refresh).blacklist()
    except TokenError:
        pass
