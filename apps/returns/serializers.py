from django.core.validators import MaxValueValidator
from rest_framework import serializers

from .models import ReturnItem, ReturnRequest

MONEY = {"max_digits": 12, "decimal_places": 2}
MAX_LINES = 50


class ReturnItemInputSerializer(serializers.Serializer):
    item_id = serializers.IntegerField(min_value=1, help_text="`items[].id` of the order.")
    quantity = serializers.IntegerField(min_value=1, validators=[MaxValueValidator(1000)])


class ReturnRequestInputSerializer(serializers.Serializer):
    """The body of `POST /orders/{order_id}/returns/`."""

    reason = serializers.ChoiceField(choices=ReturnRequest.Reason.choices)
    details = serializers.CharField(
        required=False, allow_blank=True, max_length=500, default="", help_text="Required when the reason is `other`."
    )
    items = serializers.ListField(
        child=ReturnItemInputSerializer(), allow_empty=False, max_length=MAX_LINES, help_text="Each line of the order once."
    )

    def validate_items(self, items):
        ids = [item["item_id"] for item in items]
        if len(set(ids)) != len(ids):
            raise serializers.ValidationError("Send each item once, with the number of units to return.")
        return items

    def validate(self, attrs):
        attrs["details"] = attrs.get("details", "").strip()
        if attrs["reason"] == ReturnRequest.Reason.OTHER and not attrs["details"]:
            raise serializers.ValidationError({"details": ["Please tell us what is wrong."]})
        return attrs


class ReturnItemSerializer(serializers.ModelSerializer):
    item_id = serializers.IntegerField(source="order_item_id")
    product_name = serializers.CharField(source="order_item.product_name")
    variant_label = serializers.CharField(source="order_item.variant_label")
    unit_price = serializers.DecimalField(source="order_item.unit_price", **MONEY)

    class Meta:
        model = ReturnItem
        fields = ("item_id", "product_name", "variant_label", "unit_price", "quantity")


class ReturnRequestSerializer(serializers.ModelSerializer):
    """A return request as its customer sees it: what was asked, what the shop answered, and what is paid back (the goods, less the return
    charge). What the courier costs the shop and how the units came back (fine or damaged) are the shop's own business."""

    status_display = serializers.CharField(source="get_status_display")
    reason_display = serializers.CharField(source="get_reason_display")
    items = ReturnItemSerializer(many=True, read_only=True)

    class Meta:
        model = ReturnRequest
        fields = (
            "id",
            "status",
            "status_display",
            "reason",
            "reason_display",
            "details",
            "response",
            "goods_amount",
            "return_charge",
            "refund_amount",
            "created_at",
            "updated_at",
            "items",
        )
