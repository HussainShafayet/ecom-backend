from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from . import services
from .serializers import CouponPreviewSerializer, CouponValidateSerializer

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
