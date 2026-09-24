import copy

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.catalog import pricing
from apps.catalog.models import Product, ProductMedia
from apps.catalog.queries import with_list_fields
from apps.catalog.serializers import ProductListSerializer

from .services import MAX_QUANTITY


class CartAddSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(
        min_value=1, max_value=MAX_QUANTITY, default=1, help_text="A delta, not the new total."
    )
    variant_id = serializers.IntegerField(
        min_value=1,
        required=False,
        allow_null=True,
        help_text="May be left out when the product has exactly one variant.",
    )
    action = serializers.ChoiceField(choices=["increase", "decrease"], default="increase")


class CartRefSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(min_value=1)
    variant_id = serializers.IntegerField(
        min_value=1, required=False, allow_null=True, help_text="Left out = every line of that product."
    )


class CartItemSerializer(ProductListSerializer):
    """A product card plus the cart line. `id` is the PRODUCT id. Price, image, `variant_id` and availability are
    those of the chosen variant: `cart_items()` prepares one product copy per line that way."""

    quantity = serializers.IntegerField(source="cart_quantity", read_only=True)
    color_name = serializers.SerializerMethodField()
    color_hex_code = serializers.SerializerMethodField()
    size_name = serializers.SerializerMethodField()

    class Meta(ProductListSerializer.Meta):
        fields = ProductListSerializer.Meta.fields + ("quantity", "color_name", "color_hex_code", "size_name")
        read_only_fields = fields

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_color_name(self, product):
        color = product.cart_variant.color
        return color.name if color else None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_color_hex_code(self, product):
        color = product.cart_variant.color
        return color.hex_code if color else None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_size_name(self, product):
        size = product.cart_variant.size
        return size.name if size else None


def cart_items(lines):
    """One serializable product per cart line (a product with two variants in the cart appears twice).

    The catalog's list serializer reads the price, image, variant and stock of the *default* variant from the
    annotations of the product; here they are replaced by the line's own variant, so `CartItemSerializer` needs
    no logic of its own. Three queries however many lines there are (the lines, the products, their media).
    """
    product_ids = {line.variant.product_id for line in lines}
    products = {
        product.pk: product
        for product in with_list_fields(Product.objects.filter(pk__in=product_ids)).prefetch_related("media")
    }
    items = []
    for line in lines:
        variant = line.variant
        item = copy.copy(products[variant.product_id])
        item.list_base_price, item.list_final_price = pricing.variant_prices(variant)
        item.list_variant_id = variant.pk
        item.is_available = variant.stock_quantity > 0
        if variant.color_id:  # the picture of the chosen colour, as the frontend's own cart does
            picture = next(
                (
                    media
                    for media in item.media.all()
                    if media.file_type == ProductMedia.FileType.IMAGE and media.color_id == variant.color_id
                ),
                None,
            )
            if picture:
                item.main_image = picture.file.name
        item.cart_variant = variant
        item.cart_quantity = line.quantity
        items.append(item)
    return items
