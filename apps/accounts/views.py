from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.core.responses import api_response
from apps.core.utils import mask_email, mask_phone

from . import profile_services, services
from .serializers import (
    LoginSerializer,
    LogoutSerializer,
    OTPSentSerializer,
    ProfileOTPRequestSerializer,
    ProfileOTPVerifiedSerializer,
    ProfileOTPVerifySerializer,
    ProfileSerializer,
    ProfileUpdateSerializer,
    RefreshSerializer,
    RegisterSerializer,
    ResendOTPSerializer,
    SignInSerializer,
    TokensSerializer,
    VerifyOTPSerializer,
)


class PublicAuthView(APIView):
    """Auth endpoints are open to guests. `authentication_classes = []` also means an expired or
    garbage Authorization header (the frontend sends its stale access token to refresh/logout)
    is ignored instead of causing a 401 before the view runs."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "otp_send"

    def get_authenticate_header(self, request):
        # With no authenticators DRF has no WWW-Authenticate header to send and silently turns every
        # 401 (e.g. an invalid refresh token) into a 403. The frontend and the contract need the 401.
        return 'Bearer realm="api"'


class RegisterView(PublicAuthView):
    @extend_schema(
        tags=["auth"],
        summary="Register with a phone number and send an OTP",
        request=RegisterSerializer,
        responses=OTPSentSerializer,
    )
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user, issued = services.register_user(**serializer.validated_data)
        message = issued.with_dev_hint(f"OTP sent to {mask_phone(user.phone_number)}.")
        return api_response({"token": issued.token}, message=message)


class LoginView(PublicAuthView):
    @extend_schema(
        tags=["auth"],
        summary="Start a login: send an OTP to an existing account",
        request=LoginSerializer,
        responses=OTPSentSerializer,
    )
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user, issued = services.start_login(**serializer.validated_data)
        message = issued.with_dev_hint(f"OTP sent to {mask_phone(user.phone_number)}.")
        return api_response({"token": issued.token}, message=message)


class VerifyOTPView(PublicAuthView):
    throttle_scope = "otp_verify"

    @extend_schema(
        tags=["auth"],
        summary="Verify the OTP and receive the JWT pair",
        description="Also accepts the guest's `cart` and `favorite` lists (merged by the shop apps).",
        request=VerifyOTPSerializer,
        responses=SignInSerializer,
    )
    def post(self, request):
        serializer = VerifyOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        tokens = services.complete_sign_in(
            token=data["token"], code=data["otp"], cart=data["cart"], favorites=data["favorite"]
        )
        return api_response({"tokens": tokens}, message="Signed in successfully.")


class ResendOTPView(PublicAuthView):
    @extend_schema(
        tags=["auth"],
        summary="Send a fresh OTP for an existing token",
        description="Same token, new code. Cooldown between sends (429) and a maximum number of resends (400).",
        request=ResendOTPSerializer,
        responses={200: OpenApiResponse(description="A new OTP has been sent.")},
    )
    def post(self, request):
        serializer = ResendOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        issued = services.resend_auth_otp(token=serializer.validated_data["token"])
        return api_response(None, message=issued.with_dev_hint("A new OTP has been sent."))


class TokenRefreshView(PublicAuthView):
    throttle_scope = "token"

    @extend_schema(
        tags=["auth"],
        summary="Rotate the refresh token",
        description="Returns a new `access` AND a new `refresh` (the old one is blacklisted). "
        "The frontend stores both. Invalid/expired/blacklisted refresh: 401.",
        request=RefreshSerializer,
        responses=TokensSerializer,
    )
    def post(self, request):
        serializer = RefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tokens = services.rotate_refresh_token(refresh=serializer.validated_data["refresh"])
        return api_response(dict(tokens))


class LogoutView(PublicAuthView):
    throttle_scope = "token"

    @extend_schema(
        tags=["auth"],
        summary="Revoke the refresh token",
        request=LogoutSerializer,
        responses={200: OpenApiResponse(description="Logged out (idempotent).")},
    )
    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        refresh = serializer.validated_data.get("refresh")
        if refresh:
            services.blacklist_refresh_token(refresh)
        return api_response(None, message="Logged out.")


# --- profile (authenticated: default IsAuthenticated + JWT) -------------------------------------------
class ProfileView(APIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @extend_schema(tags=["profile"], summary="Get my profile", responses=ProfileSerializer)
    def get(self, request):
        return api_response(ProfileSerializer(request.user, context={"request": request}).data)

    @extend_schema(
        tags=["profile"],
        summary="Update my profile (partial)",
        description="Send only what changed, as multipart (needed for `profile_picture`) or JSON. "
        "A new `phone_number` or `email` is accepted only after it was verified through "
        "`request-otp/` + `verify-otp-for-profile/` (within a limited time, once per verification).",
        request={
            "multipart/form-data": ProfileUpdateSerializer,
            "application/json": ProfileUpdateSerializer,
        },
        responses=ProfileSerializer,
    )
    def put(self, request):
        serializer = ProfileUpdateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = profile_services.update_profile(user=request.user, data=serializer.validated_data)
        return api_response(
            ProfileSerializer(user, context={"request": request}).data, message="Profile updated."
        )

    @extend_schema(exclude=True)  # PATCH is an alias of PUT (both are partial); document only PUT
    def patch(self, request):
        return self.put(request)


class ProfileOTPView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "otp_send"


class ProfileOTPRequestView(ProfileOTPView):
    @extend_schema(
        tags=["profile"],
        summary="Send an OTP to a NEW phone number or email",
        request=ProfileOTPRequestSerializer,
        responses=OTPSentSerializer,
    )
    def post(self, request):
        serializer = ProfileOTPRequestSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        field, value = serializer.validated_data["field"], serializer.validated_data["value"]
        issued = profile_services.start_change_verification(user=request.user, field=field, value=value)
        masked = mask_phone(value) if field == "phone_number" else mask_email(value)
        return api_response({"token": issued.token}, message=issued.with_dev_hint(f"OTP sent to {masked}."))


class ProfileOTPVerifyView(ProfileOTPView):
    throttle_scope = "otp_verify"

    @extend_schema(
        tags=["profile"],
        summary="Verify the OTP sent for a profile change",
        description="Wrong OTP is a 400 (never 401). After this succeeds, save the value with PUT /profile/.",
        request=ProfileOTPVerifySerializer,
        responses=ProfileOTPVerifiedSerializer,
    )
    def post(self, request):
        serializer = ProfileOTPVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        field, value = profile_services.verify_change(
            user=request.user,
            token=serializer.validated_data["token"],
            code=serializer.validated_data["otp"],
        )
        return api_response(
            {"field": field, "value": value},
            message="Verified. Save your profile to apply the change.",
        )
