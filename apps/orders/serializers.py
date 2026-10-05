from django.conf import settings
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.accounts.validators import phone_number_validator
from apps.addresses.models import Address
from apps.addresses.serializers import LOCATION_FIELDS, REQUIRED_BY_TYPE, AddressSerializer
from apps.cart.services import MAX_QUANTITY
from apps.catalog.serializers import absolute_url

from .models import Order, OrderItem, OrderStatusHistory
from . import hooks, services
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
    coupon_code = serializers.CharField(
        required=False, allow_blank=True, max_length=40, help_text="Optional. A bad or expired code is a 400."
    )

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
        attrs["coupon_code"] = attrs.get("coupon_code") or ""
        return attrs


class ExpectedDeliverySerializer(serializers.Serializer):
    """When to expect an order, as the customer was told when they placed it (calendar days from that day)."""

    earliest = serializers.DateField()
    latest = serializers.DateField()


class OrderPlacedSerializer(serializers.Serializer):
    """What `POST /orders/` answers. The frontend reads `order_id`; the rest is what the confirmation page shows."""

    order_id = serializers.CharField(help_text="The human-readable order number, e.g. GC-20260923-0001 (URL-safe).")
    status = serializers.CharField()
    created_at = serializers.DateTimeField()
    subtotal = serializers.DecimalField(**MONEY)
    delivery_charge = serializers.DecimalField(**MONEY)
    discount_amount = serializers.DecimalField(**MONEY, help_text="What the coupon took off. 0 when there was none.")
    coupon_code = serializers.CharField(help_text='"" when no coupon was used.')
    total = serializers.DecimalField(**MONEY)
    expected_delivery = ExpectedDeliverySerializer(
        allow_null=True, help_text="null when the shop made no estimate for this shipping type."
    )


# --- reading an order (a customer's own, or a guest's tracking) ---------------------------------------------------
class OrderItemSerializer(serializers.ModelSerializer):
    """One line, as it was bought (the snapshot), plus the product's current picture and slug for the link. `product_id` and
    `variant_id` say what to put in a cart to buy it again (null when that product or variant has been deleted since); `id` names
    the line when part of the order is to be returned."""

    product_slug = serializers.SerializerMethodField(help_text="null when the product has been deleted since.")
    image = serializers.SerializerMethodField(help_text="Absolute URL of the product's main image, or null.")

    class Meta:
        model = OrderItem
        fields = (
            "id",
            "product_id",
            "variant_id",
            "product_slug",
            "product_name",
            "variant_label",
            "sku",
            "unit_price",
            "base_price",
            "quantity",
            "line_total",
            "image",
        )

    def get_product_slug(self, item) -> str | None:
        return self.context.get("slugs", {}).get(item.product_id)

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_image(self, item):
        name = self.context.get("images", {}).get(item.product_id)
        return absolute_url(self.context.get("request"), name) if name else None


class OrderStepSerializer(serializers.ModelSerializer):
    """One step of the status history: the status the order moved to, and when. Who moved it and the staff's note are
    not shown."""

    status = serializers.CharField(source="to_status")
    status_display = serializers.CharField(source="get_to_status_display")

    class Meta:
        model = OrderStatusHistory
        fields = ("status", "status_display", "created_at")


class OrderPaymentSerializer(serializers.Serializer):
    """Documentation of the `payment` block (its source is the payments app, see `orders/hooks.py`)."""

    method = serializers.CharField()
    method_display = serializers.CharField()
    status = serializers.CharField(help_text="pending | paid | cancelled | refunded")
    status_display = serializers.CharField()
    amount = serializers.DecimalField(**MONEY)
    paid_at = serializers.DateTimeField(allow_null=True)
    refunded_at = serializers.DateTimeField(allow_null=True)


class ReturnReasonSerializer(serializers.Serializer):
    value = serializers.CharField()
    label = serializers.CharField()
    free = serializers.BooleanField(help_text="True when sending the goods back for this reason costs the customer nothing.")


class ReturnableItemSerializer(serializers.Serializer):
    item_id = serializers.IntegerField(help_text="`items[].id` of the order.")
    quantity = serializers.IntegerField(help_text="Units of that line that may still be returned.")


class ReturnRequestItemSerializer(serializers.Serializer):
    item_id = serializers.IntegerField()
    product_name = serializers.CharField()
    variant_label = serializers.CharField()
    unit_price = serializers.DecimalField(**MONEY)
    quantity = serializers.IntegerField()


class ReturnRequestSerializer(serializers.Serializer):
    """Documentation of one entry of `returns.requests` (its source is the returns app, see `orders/hooks.py`)."""

    id = serializers.IntegerField()
    status = serializers.CharField(help_text="requested | approved | received | rejected | completed | cancelled")
    status_display = serializers.CharField()
    reason = serializers.CharField(help_text="damaged | wrong_item | not_as_described | size_fit | changed_mind | other")
    reason_display = serializers.CharField()
    details = serializers.CharField(help_text='What the customer wrote; "" when nothing.')
    response = serializers.CharField(help_text='The shop\'s message to the customer; "" until it has written one.')
    goods_amount = serializers.DecimalField(**MONEY, help_text="The price of the returned lines, less their share of the coupon.")
    return_charge = serializers.DecimalField(**MONEY, help_text="What the customer pays of the courier cost, taken off the refund (0 = free return).")
    refund_amount = serializers.DecimalField(**MONEY, help_text="What is paid back: the goods less the return charge. An estimate until the request is completed.")
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    items = ReturnRequestItemSerializer(many=True)


class OrderReturnsSerializer(serializers.Serializer):
    """Documentation of the `returns` block (its source is the returns app, see `orders/hooks.py`)."""

    can_request = serializers.BooleanField(
        help_text="True when the order is delivered, the shop takes returns, the return period is open and something is left to return."
    )
    message = serializers.CharField(
        allow_null=True, help_text="Why a delivered order can not be returned now (null otherwise, or while it can)."
    )
    until = serializers.DateField(allow_null=True, help_text="The last day a return may be asked for (delivered orders only).")
    return_charge = serializers.DecimalField(
        **MONEY, help_text="What a reason that is not `free` costs the customer (the order's delivery charge), taken off the refund; 0 when the shop charges nothing."
    )
    reasons = ReturnReasonSerializer(many=True, help_text="What the customer chooses from.")
    items = ReturnableItemSerializer(many=True, help_text="The lines (and units) that may be returned: empty unless `can_request`.")
    requests = ReturnRequestSerializer(many=True, help_text="The customer's requests for this order, newest first.")


class OrderSummarySerializer(serializers.ModelSerializer):
    """A row of the customer's order list."""

    order_id = serializers.CharField(source="number", help_text="e.g. GC-20260923-0001; use it in /orders/{order_id}/.")
    status_display = serializers.CharField(source="get_status_display")
    items_count = serializers.SerializerMethodField(
        help_text="Units, not lines: two of one product and one of another is 3."
    )
    items = OrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = ("order_id", "status", "status_display", "created_at", "total", "items_count", "items")

    def get_items_count(self, order) -> int:
        return sum(item.quantity for item in order.items.all())


class OrderDetailSerializer(OrderSummarySerializer):
    """One of the customer's own orders, in full."""

    payment = serializers.SerializerMethodField(help_text="null when the order has no payment record.")
    history = serializers.SerializerMethodField(help_text="Every status the order has been in, oldest first.")
    can_cancel = serializers.SerializerMethodField(
        help_text="True while the order is pending: only then may the customer cancel it."
    )
    coupon_code = serializers.SerializerMethodField(help_text='"" when no coupon was used.')
    expected_delivery = serializers.SerializerMethodField(
        help_text="`{earliest, latest}` dates while the order is on its way and the shop made an estimate, else null."
    )
    returns = serializers.SerializerMethodField(help_text="null when the shop has no return requests feature installed.")

    class Meta(OrderSummarySerializer.Meta):
        fields = OrderSummarySerializer.Meta.fields + (
            "name",
            "email",
            "phone_number",
            "shipping_type",
            "shipping_area",
            "shipping_division",
            "shipping_district",
            "shipping_thana",
            "shipping_address",
            "subtotal",
            "delivery_charge",
            "discount_amount",
            "coupon_code",
            "payment",
            "history",
            "can_cancel",
            "expected_delivery",
            "returns",
        )

    @extend_schema_field(OrderPaymentSerializer(allow_null=True))
    def get_payment(self, order):
        return self.context.get("payments", {}).get(order.pk)

    @extend_schema_field(OrderReturnsSerializer(allow_null=True))
    def get_returns(self, order):
        return hooks.returns_info(order)

    @extend_schema_field(OrderStepSerializer(many=True))
    def get_history(self, order):
        return OrderStepSerializer(order.history.all(), many=True).data

    def get_can_cancel(self, order) -> bool:
        return order.status == Order.Status.PENDING

    def get_coupon_code(self, order) -> str:
        return order.coupon.code if order.coupon_id else ""

    @extend_schema_field(ExpectedDeliverySerializer(allow_null=True))
    def get_expected_delivery(self, order):
        expected = services.expected_delivery(order)
        return ExpectedDeliverySerializer(expected).data if expected else None


class OrderTrackingSerializer(OrderDetailSerializer):
    """What a guest gets for an order number and its phone number: the progress and what was ordered, nothing about
    who it is for or where it goes (an order number is easy to guess; the phone number is the only secret)."""

    class Meta(OrderSummarySerializer.Meta):
        fields = OrderSummarySerializer.Meta.fields + (
            "subtotal", "delivery_charge", "discount_amount", "coupon_code", "payment", "history", "expected_delivery"
        )


class OrderListQuerySerializer(serializers.Serializer):
    """The query of `GET /orders/`: which statuses to keep."""

    status = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="One status, or several separated by commas: " + ", ".join(Order.Status.values) + ".",
    )

    def validate_status(self, value):
        wanted = [part.strip().lower() for part in value.split(",") if part.strip()]
        unknown = [part for part in wanted if part not in Order.Status.values]
        if unknown:
            raise serializers.ValidationError(f"Unknown status: {', '.join(unknown)}.")
        return list(dict.fromkeys(wanted))

    def validate(self, attrs):
        attrs.setdefault("status", [])
        return attrs


class OrderTrackingQuerySerializer(serializers.Serializer):
    order_id = serializers.CharField(max_length=40)
    phone_number = serializers.CharField(max_length=14, validators=[phone_number_validator])

    def validate_order_id(self, value):
        return value.strip().upper()  # people type it in lower case


class DeliveryChargesSerializer(serializers.Serializer):
    inside_dhaka = serializers.DecimalField(required=False, **MONEY)
    outside_dhaka = serializers.DecimalField(required=False, **MONEY)


class UserInfoSerializer(serializers.Serializer):
    name = serializers.CharField()
    phone_number = serializers.CharField()
    email = serializers.CharField(help_text='"" when the customer has none.')


class DeliveryEstimateSerializer(serializers.Serializer):
    min_days = serializers.IntegerField()
    max_days = serializers.IntegerField()


class DeliveryEstimatesSerializer(serializers.Serializer):
    inside_dhaka = DeliveryEstimateSerializer(required=False)
    outside_dhaka = DeliveryEstimateSerializer(required=False)


class CheckoutContentSerializer(serializers.Serializer):
    delivery_charges = DeliveryChargesSerializer(
        help_text="A shipping type without a configured charge is left out (ordering with it is a 400)."
    )
    delivery_estimates = DeliveryEstimatesSerializer(
        help_text="How many calendar days delivery takes, per shipping type: only for a type the shop made an estimate for."
    )
    shipping_addresses = AddressSerializer(many=True, help_text="The customer's saved addresses; [] for a guest.")
    user_info = UserInfoSerializer(allow_null=True, help_text="null for a guest.")
