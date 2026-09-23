from rest_framework import serializers

from .validators import phone_number_validator

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
