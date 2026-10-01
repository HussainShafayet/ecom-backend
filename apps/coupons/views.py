from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from . import services
from .serializers import (
    CouponAvailableQuerySerializer,
    CouponOffersSerializer,
    CouponPreviewSerializer,
    CouponValidateSerializer,
)

TAGS = ["coupons"]


class CouponValidateView(APIView):
    """Public: preview a coupon's discount before placing the order (the checkout/cart promo-code field). `POST
    /orders/` also accepts `coupon_code` directly, so a coupon works even without calling this first."""

    authentication_classes = []  # who is asking does not matter, so a stale token can not turn this into a 401
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "coupon"

    @extend_schema(
        tags=TAGS,
        summary="Preview a coupon's discount against a subtotal (guests too)",
        description="`subtotal` is only what the cart already shows, to preview the discount: placing the order "
        "recomputes everything from the database. A bad, expired, exhausted or already-used code is a 400 with "
        "one sentence in `errors`.",
        request=CouponValidateSerializer,
        responses=CouponPreviewSerializer,
        auth=[],
    )
    def post(self, request):
        serializer = CouponValidateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        coupon = services.validate_coupon(data["code"], data["subtotal"], data.get("phone_number"))
        discount = services.compute_discount(coupon, data["subtotal"])
        return Response(CouponPreviewSerializer({"discount_amount": discount, "total": data["subtotal"] - discount}).data)


class CouponAvailableView(APIView):
    """Public: the coupons the shop suggests at checkout, so a customer does not have to know a code."""

    authentication_classes = []  # who is asking does not matter, so a stale token can not turn this into a 401
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "coupon_offers"

    @extend_schema(
        tags=TAGS,
        summary="The coupons suggested at checkout, for a cart's subtotal (guests too)",
        description="Only coupons the staff ticked *show at checkout* and that can be used right now (switched on, inside "
        "their dates, uses left), at most 5: the ones usable now first, then the biggest saving. `eligible` is false while "
        "`subtotal` is below `min_order_amount`, and `amount_short` is what is missing. Secret codes are never listed, "
        "and a per-customer limit is only checked once the phone number is given to `POST /coupons/validate/`. The "
        "answer is a hint: `POST /orders/` decides, always.",
        parameters=[CouponAvailableQuerySerializer],
        responses=CouponOffersSerializer,
        auth=[],
    )
    def get(self, request):
        query = CouponAvailableQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        offers = services.available_offers(query.validated_data["subtotal"])
        return Response(CouponOffersSerializer({"offers": offers}).data)
