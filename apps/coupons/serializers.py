from rest_framework import serializers

MONEY = {"max_digits": 12, "decimal_places": 2}


class CouponValidateSerializer(serializers.Serializer):
    """The body of `POST /coupons/validate/`. `subtotal` is the cart's own subtotal (what the page already shows),
    used only to preview the discount; placing the order recomputes everything from the database and ignores it."""

    code = serializers.CharField(max_length=40)
    subtotal = serializers.DecimalField(min_value=0, **MONEY)
    phone_number = serializers.CharField(required=False, allow_blank=True, max_length=14)

    def validate_phone_number(self, value):
        return value or None


class CouponPreviewSerializer(serializers.Serializer):
    """What `POST /coupons/validate/` answers."""

    discount_amount = serializers.DecimalField(**MONEY)
    total = serializers.DecimalField(**MONEY, help_text="subtotal - discount_amount.")
