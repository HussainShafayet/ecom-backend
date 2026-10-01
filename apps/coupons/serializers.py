from rest_framework import serializers

from apps.catalog.models import DiscountType

MONEY = {"max_digits": 12, "decimal_places": 2}


class CouponValidateSerializer(serializers.Serializer):
    """The body of `POST /coupons/validate/`. `subtotal` is the cart's own subtotal (what the page already shows),
    used only to preview the discount; placing the order recomputes everything from the database and ignores it."""

    code = serializers.CharField(max_length=40)
    subtotal = serializers.DecimalField(min_value=0, **MONEY)
    phone_number = serializers.CharField(required=False, allow_blank=True, max_length=14)

    def validate_phone_number(self, value):
        return value or None


class CouponAvailableQuerySerializer(serializers.Serializer):
    """The query of `GET /coupons/available/`: the cart's subtotal, to tell which offers are within reach."""

    subtotal = serializers.DecimalField(min_value=0, required=False, default=0, **MONEY)


class CouponOfferSerializer(serializers.Serializer):
    """One coupon the shop suggests at checkout (`GET /coupons/available/`)."""

    code = serializers.CharField()
    public_title = serializers.CharField(help_text="What the customer reads, e.g. '25% off your first order'.")
    discount_type = serializers.ChoiceField(choices=DiscountType.choices)
    discount_value = serializers.DecimalField(**MONEY, help_text="A percentage (0-100) or a fixed amount, by discount_type.")
    min_order_amount = serializers.DecimalField(**MONEY, allow_null=True, help_text="Null: no minimum.")
    max_discount_amount = serializers.DecimalField(**MONEY, allow_null=True, help_text="Null: no cap.")
    eligible = serializers.BooleanField(help_text="True when the subtotal already reaches min_order_amount.")
    amount_short = serializers.DecimalField(**MONEY, help_text="What the cart still needs to reach min_order_amount; 0 when eligible.")


class CouponOffersSerializer(serializers.Serializer):
    """What `GET /coupons/available/` answers."""

    offers = CouponOfferSerializer(many=True)


class CouponPreviewSerializer(serializers.Serializer):
    """What `POST /coupons/validate/` answers."""

    discount_amount = serializers.DecimalField(**MONEY)
    total = serializers.DecimalField(**MONEY, help_text="subtotal - discount_amount.")
