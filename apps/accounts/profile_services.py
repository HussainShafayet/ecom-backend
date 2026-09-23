"""Profile edits. A new phone number or email only sticks after the user proved they own it with an OTP."""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import OTPRequest
from .otp import service as otp_service

User = get_user_model()
Purpose = OTPRequest.Purpose

PROFILE_PURPOSES = (Purpose.PROFILE_PHONE, Purpose.PROFILE_EMAIL)
FIELD_PURPOSE = {"phone_number": Purpose.PROFILE_PHONE, "email": Purpose.PROFILE_EMAIL}
FIELD_LABEL = {"phone_number": "phone number", "email": "email address"}
PURPOSE_FIELD = {purpose: field for field, purpose in FIELD_PURPOSE.items()}


def _others(queryset, user):
    return queryset.exclude(pk=user.pk) if user is not None else queryset


def phone_in_use(phone, *, exclude=None):
    return _others(User.objects.filter(phone_number=phone), exclude).exists()


def email_in_use(email, *, exclude=None):
    return _others(User.objects.filter(email__iexact=email), exclude).exists()


def username_in_use(username, *, exclude=None):
    return _others(User.objects.filter(username__iexact=username), exclude).exists()


def start_change_verification(*, user, field, value):
    """Send an OTP to the NEW phone/email. Returns the opaque token."""
    return otp_service.start_otp(user=user, purpose=FIELD_PURPOSE[field], target=value)


def verify_change(*, user, token, code):
    """Check the code. Returns (field, value) that is now allowed to be saved on the profile."""
    otp = otp_service.verify_otp(token=token, code=code, purposes=PROFILE_PURPOSES, user=user)
    return PURPOSE_FIELD[otp.purpose], otp.target


def _use_verification(user, field, value):
    """Spend one recent, unused verification of exactly this value, or refuse the change."""
    now = timezone.now()
    window_start = now - timedelta(seconds=settings.PROFILE_VERIFICATION_WINDOW_SECONDS)
    otp = (
        OTPRequest.objects.select_for_update()
        .filter(
            user=user,
            purpose=FIELD_PURPOSE[field],
            target=value,
            consumed_at__gte=window_start,
            applied_at__isnull=True,
        )
        .order_by("-consumed_at")
        .first()
    )
    if otp is None:
        raise ValidationError(
            {field: [f"Verify this {FIELD_LABEL[field]} with an OTP before saving it."]}
        )
    otp.applied_at = now
    otp.save(update_fields=["applied_at"])


def update_profile(*, user, data):
    """Apply already-validated profile fields and return the refreshed user."""
    old_picture = storage = None
    try:
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=user.pk)

            if "phone_number" in data and data["phone_number"] != user.phone_number:
                _use_verification(user, "phone_number", data["phone_number"])
                user.phone_number = data["phone_number"]
                user.is_phone_verified = True

            if "email" in data and data["email"] != user.email:
                if data["email"]:
                    _use_verification(user, "email", data["email"])
                user.email = data["email"]  # None removes it (no OTP needed to delete)
                user.is_email_verified = bool(data["email"])

            for field in ("name", "date_of_birth", "gender"):
                if field in data:
                    setattr(user, field, data[field])
            if "username" in data:
                user.username = data["username"]

            if data.get("profile_picture"):
                if user.profile_picture:
                    old_picture, storage = user.profile_picture.name, user.profile_picture.storage
                user.profile_picture = data["profile_picture"]

            user.save()
            if old_picture:  # only after the new picture is safely committed
                transaction.on_commit(lambda: storage.delete(old_picture))
    except IntegrityError as exc:  # lost a race for a unique value
        raise ValidationError("That value is already used by another account.") from exc
    return user
