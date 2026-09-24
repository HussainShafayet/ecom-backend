from django.conf import settings
from rest_framework import serializers

from apps.accounts.validators import phone_number_validator
from apps.addresses.models import Address
from apps.addresses.serializers import LOCATION_FIELDS, REQUIRED_BY_TYPE, AddressSerializer
from apps.cart.services import MAX_QUANTITY

from .services import PAYMENT_TYPES

MONEY = {"max_digits": 12, "decimal_places": 2}


class OrderItemInputSerializer(serializers.Serializer):
    """A line of the order. The frontend also sends the `price` it shows: it is ignored, the server prices the line."""

    product_id = serializers.IntegerField(min_value=1)
    variant_id = serializers.IntegerField(
        min_value=1,
        required=False,
        allow_null=True,
        help_text="May be left out when the product has exactly one variant.",
    )
    quantity = serializers.IntegerField(min_value=1, max_value=MAX_QUANTITY)


class OrderItemsField(serializers.ListField):
    """The lines of the order: at least one, at most `settings.MAX_CART_LINES` (read on every request, and checked
    before the lines are looked at, so a huge list is refused cheaply)."""

    child = OrderItemInputSerializer()
    default_error_messages = {"too_many": "An order can hold at most {limit} different items."}

    def __init__(self, **kwargs):
        kwargs.setdefault("allow_empty", False)
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        limit = settings.MAX_CART_LINES
        if isinstance(data, list) and len(data) > limit:
            self.fail("too_many", limit=limit)
        return super().to_internal_value(data)


class PlaceOrderSerializer(serializers.Serializer):
    """The body of `POST /orders/`. Keys that are not listed (`price`, `sub_total_price`, `delivery_charge`,
    `total_price`, `shipping`, ...) are ignored: prices and totals always come from the database."""

    name = serializers.CharField(max_length=150)
    email = serializers.EmailField(required=False, allow_blank=True, allow_null=True, max_length=254)
    phone_number = serializers.CharField(max_length=14, validators=[phone_number_validator])
    shipping_type = serializers.ChoiceField(choices=Address.ShippingType.choices)
    shipping_area = serializers.CharField(required=False, allow_blank=True, max_length=100)
    shipping_division = serializers.CharField(required=False, allow_blank=True, max_length=100)
    shipping_district = serializers.CharField(required=False, allow_blank=True, max_length=100)
    shipping_thana = serializers.CharField(required=False, allow_blank=True, max_length=100)
    shipping_address = serializers.CharField(max_length=500)
    payment_type = serializers.ChoiceField(
        choices=[(name, method.label) for name, method in PAYMENT_TYPES.items()],
        default="cash",
        help_text='"cash" and "cod" both mean cash on delivery.',
    )
    items = OrderItemsField()

    def validate(self, attrs):
        # Same rule as a saved address: inside Dhaka needs the area, outside needs division, district and thana,
        # and what does not apply to the chosen type is cleared (the frontend may leave stale values behind).
        needed = {f"shipping_{name}" for name in REQUIRED_BY_TYPE[attrs["shipping_type"]]}
        errors = {name: ["This field is required."] for name in needed if not attrs.get(name, "").strip()}
        if errors:
            raise serializers.ValidationError(errors)
        for name in (f"shipping_{name}" for name in LOCATION_FIELDS):
            if name not in needed:
                attrs[name] = ""
        attrs["email"] = attrs.get("email") or ""
        return attrs


class OrderPlacedSerializer(serializers.Serializer):
    order_id = serializers.CharField(help_text="The human-readable order number, e.g. GC-20260923-0001 (URL-safe).")


class DeliveryChargesSerializer(serializers.Serializer):
    inside_dhaka = serializers.DecimalField(required=False, **MONEY)
    outside_dhaka = serializers.DecimalField(required=False, **MONEY)


class UserInfoSerializer(serializers.Serializer):
    name = serializers.CharField()
    phone_number = serializers.CharField()
    email = serializers.CharField(help_text='"" when the customer has none.')


class CheckoutContentSerializer(serializers.Serializer):
    delivery_charges = DeliveryChargesSerializer(
        help_text="A shipping type without a configured charge is left out (ordering with it is a 400)."
    )
    shipping_addresses = AddressSerializer(many=True, help_text="The customer's saved addresses; [] for a guest.")
    user_info = UserInfoSerializer(allow_null=True, help_text="null for a guest.")
