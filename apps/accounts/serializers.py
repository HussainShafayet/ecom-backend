from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers

from apps.core.validators import validate_image_upload

from . import profile_services
from .profile_services import FIELD_LABEL
from .validators import phone_number_validator, username_validator

User = get_user_model()
PHONE_IN_USE = "This phone number is already used by another account."
EMAIL_IN_USE = "This email is already used by another account."

MAX_GUEST_ITEMS = 100


class PhoneNumberField(serializers.CharField):
    def __init__(self, **kwargs):
        kwargs.setdefault("max_length", 14)
        kwargs.setdefault("validators", [phone_number_validator])
        super().__init__(**kwargs)


class RegisterSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    phone_number = PhoneNumberField()
    email = serializers.EmailField(required=False, allow_blank=True, allow_null=True, default=None)


class LoginSerializer(serializers.Serializer):
    # The frontend also sends `expiresInMins`; unknown keys are ignored.
    phone_number = PhoneNumberField()


class OTPCodeField(serializers.RegexField):
    def __init__(self, **kwargs):
        super().__init__(
            r"^\d{6}$", error_messages={"invalid": "Must be a 6-digit number."}, **kwargs
        )


class VerifyOTPSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=200)
    otp = OTPCodeField()
    # Whatever the guest had in the browser. Deliberately lenient: a malformed entry must never stop
    # someone from signing in, and the receivers (cart/wishlist apps) sanitise each item themselves.
    cart = serializers.ListField(
        child=serializers.DictField(), required=False, default=list, max_length=MAX_GUEST_ITEMS
    )
    favorite = serializers.ListField(  # note: the frontend spells it "favorite"
        child=serializers.DictField(), required=False, default=list, max_length=MAX_GUEST_ITEMS
    )


class ResendOTPSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=200)


class RefreshSerializer(serializers.Serializer):
    # `expiresInMins` is ignored. The Authorization header (an expired access token) is ignored too.
    refresh = serializers.CharField()


class LogoutSerializer(serializers.Serializer):
    # Both optional: the frontend logs out locally no matter what, so this call is best effort.
    access = serializers.CharField(required=False, allow_blank=True)
    refresh = serializers.CharField(required=False, allow_blank=True)


# --- response shapes (documentation only; views return plain dicts) ---------------------------------
class OTPSentSerializer(serializers.Serializer):
    token = serializers.CharField(help_text="Opaque URL-safe token; send it back with the OTP.")


class TokensSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()


class SignInSerializer(serializers.Serializer):
    tokens = TokensSerializer()


# --- profile ------------------------------------------------------------------------------------------
class ProfileSerializer(serializers.ModelSerializer):
    """What GET/PUT /accounts/profile/ return (exactly the keys the frontend reads)."""

    class Meta:
        model = User
        fields = (
            "name",
            "username",
            "email",
            "phone_number",
            "date_of_birth",
            "gender",
            "profile_picture",
        )
        read_only_fields = fields


class ProfileUpdateSerializer(serializers.Serializer):
    """Every field optional: the frontend sends only what changed (or just `profile_picture`).

    phone_number / email are format-checked here; whether they were OTP-verified is enforced when saving.
    Unknown keys (is_staff, id, ...) are ignored.
    """

    name = serializers.CharField(max_length=150, required=False)
    username = serializers.CharField(
        max_length=50, required=False, allow_blank=True, allow_null=True, validators=[username_validator]
    )
    email = serializers.EmailField(required=False, allow_blank=True, allow_null=True)
    phone_number = PhoneNumberField(required=False)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    gender = serializers.ChoiceField(choices=User.Gender.choices, required=False, allow_blank=True)
    profile_picture = serializers.ImageField(required=False, validators=[validate_image_upload])

    def validate_username(self, value):
        return value.strip() if value and value.strip() else None

    def validate_email(self, value):
        return value.strip().lower() if value and value.strip() else None

    def validate_date_of_birth(self, value):
        if value and (value > timezone.localdate() or value.year < 1900):
            raise serializers.ValidationError("Enter a valid date of birth.")
        return value

    def validate(self, attrs):
        user = self.context["request"].user
        errors = {}
        if attrs.get("username") and profile_services.username_in_use(attrs["username"], exclude=user):
            errors["username"] = ["This username is already taken."]
        if attrs.get("email") and attrs["email"] != user.email:
            if profile_services.email_in_use(attrs["email"], exclude=user):
                errors["email"] = [EMAIL_IN_USE]
        if "phone_number" in attrs and attrs["phone_number"] != user.phone_number:
            if profile_services.phone_in_use(attrs["phone_number"], exclude=user):
                errors["phone_number"] = [PHONE_IN_USE]
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


class ProfileOTPRequestSerializer(serializers.Serializer):
    """Ask for an OTP to verify a NEW phone number or email (exactly one of them)."""

    phone_number = PhoneNumberField(required=False)
    email = serializers.EmailField(required=False)

    def validate(self, attrs):
        user = self.context["request"].user
        given = [name for name in ("phone_number", "email") if attrs.get(name)]
        if len(given) != 1:
            raise serializers.ValidationError("Provide either a phone number or an email address, not both.")
        field = given[0]
        value = attrs[field].strip()
        if field == "email":
            value = value.lower()

        if value == getattr(user, field):
            raise serializers.ValidationError({field: [f"This is already your {FIELD_LABEL[field]}."]})
        in_use = profile_services.phone_in_use if field == "phone_number" else profile_services.email_in_use
        if in_use(value, exclude=user):
            raise serializers.ValidationError(
                {field: [PHONE_IN_USE if field == "phone_number" else EMAIL_IN_USE]}
            )
        return {"field": field, "value": value}


class ProfileOTPVerifySerializer(serializers.Serializer):
    token = serializers.CharField(max_length=200)
    otp = OTPCodeField()


class ProfileOTPVerifiedSerializer(serializers.Serializer):
    field = serializers.ChoiceField(choices=["phone_number", "email"])
    value = serializers.CharField()
