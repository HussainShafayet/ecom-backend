"""Read-only shapes the React shop expects (see docs/API_CONTRACT.md section 5). The querysets come from
`queries.with_list_fields`, which supplies the annotated values these serializers read."""
from django.core.files.storage import default_storage
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from . import pricing
from .models import Category, Product, ProductMedia

MONEY = {"max_digits": 12, "decimal_places": 2}


def absolute_url(request, file):
    """Absolute URL of a stored file (a FieldFile or a bare storage name), or None when there is none.
    The frontend lives on another origin, so a media URL is never relative."""
    name = getattr(file, "name", file)
    if not name:
        return None
    url = default_storage.url(name)
    return request.build_absolute_uri(url) if request is not None else url


class OptionalMethodField(serializers.SerializerMethodField):
    """A method field that the OpenAPI schema lists as optional (the serializer leaves it out of some responses;
    spectacular otherwise marks every read-only field as always present)."""

    def __init__(self, method_name=None, **kwargs):
        super().__init__(method_name, **kwargs)
        self.read_only = False
        self.required = False


class ProductListSerializer(serializers.ModelSerializer):
    """One product card. Prices are those of the default variant (what the card adds to the cart)."""

    image = serializers.SerializerMethodField()
    base_price = serializers.DecimalField(source="list_base_price", read_only=True, **MONEY)
    discount_price = serializers.DecimalField(
        source="list_final_price", read_only=True, help_text="What the customer pays; equals base_price without a discount.", **MONEY
    )
    has_discount = serializers.SerializerMethodField()
    discount_type = serializers.SerializerMethodField()
    brand_name = serializers.SerializerMethodField()
    availability_status = serializers.BooleanField(source="is_available", read_only=True)
    has_variants = serializers.BooleanField(
        source="has_options", read_only=True, help_text="True when the customer has to pick a colour or size."
    )
    variant_id = serializers.IntegerField(source="list_variant_id", read_only=True, allow_null=True)
    is_favourite = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = (
            "id",
            "name",
            "slug",
            "sku",
            "image",
            "base_price",
            "discount_price",
            "has_discount",
            "discount_type",
            "discount_value",
            "brand_name",
            "total_views",
            "total_orders",
            "total_reviews",
            "avg_rating",
            "availability_status",
            "has_variants",
            "variant_id",
            "minimum_order_quantity",
            "is_favourite",
        )
        read_only_fields = fields

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_image(self, product):
        return absolute_url(self.context.get("request"), product.main_image)

    def get_has_discount(self, product) -> bool:
        return product.list_final_price < product.list_base_price

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_discount_type(self, product):
        return product.discount_type or None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_brand_name(self, product):
        return product.brand.name if product.brand_id else None

    def get_is_favourite(self, product) -> bool:
        return product.pk in self.context.get("favourite_ids", ())


# --- product detail ----------------------------------------------------------------------------------------


class NameSerializer(serializers.Serializer):
    name = serializers.CharField()


class CategoryRefSerializer(serializers.Serializer):
    name = serializers.CharField()
    slug = serializers.SlugField()


class DimensionSerializer(serializers.Serializer):
    width = serializers.DecimalField(max_digits=8, decimal_places=2, allow_null=True)
    height = serializers.DecimalField(max_digits=8, decimal_places=2, allow_null=True)
    depth = serializers.DecimalField(max_digits=8, decimal_places=2, allow_null=True)


class MediaFileSerializer(serializers.Serializer):
    file_type = serializers.ChoiceField(choices=ProductMedia.FileType.choices)
    file_url = serializers.URLField()
    thumbnail_url = serializers.URLField(allow_null=True, help_text="A video has one only when a poster was uploaded.")


class SizeOptionSerializer(serializers.Serializer):
    name = serializers.CharField()
    variant_id = serializers.IntegerField()
    base_price = serializers.DecimalField(**MONEY)
    discount_price = serializers.DecimalField(**MONEY)
    availability_status = serializers.BooleanField()


class ColorOptionSerializer(serializers.Serializer):
    name = serializers.CharField()
    hex_code = serializers.CharField()
    media_files = MediaFileSerializer(many=True, help_text="The colour's own media, else the shared product media.")
    sizes = SizeOptionSerializer(many=True)
    # Only for a colour that is sold without a size (then `sizes` is empty):
    variant_id = serializers.IntegerField(required=False)
    base_price = serializers.DecimalField(required=False, **MONEY)
    discount_price = serializers.DecimalField(required=False, **MONEY)
    availability_status = serializers.BooleanField(required=False)


def _media_entries(media, request):
    return [
        {
            "file_type": item.file_type,
            "file_url": absolute_url(request, item.file),
            "thumbnail_url": absolute_url(request, item.thumbnail),
        }
        for item in media
    ]


def _size_entry(variant):
    base, final = pricing.variant_prices(variant)
    return {
        "name": variant.size.name,
        "variant_id": variant.pk,
        "base_price": base,
        "discount_price": final,
        "availability_status": variant.stock_quantity > 0,
    }


def _sorted_sizes(variants):
    ordered = sorted((v for v in variants if v.size_id is not None), key=lambda v: (v.size.sort_order, v.size.name, v.pk))
    return [_size_entry(variant) for variant in ordered]


def build_options(product, request):
    """(colors, sizes, media_files) of a product from its prefetched `active_variants` and `media`.

    - some variants have a colour: `colors` (each with its sizes), `sizes` is empty and `media_files` is the shared
      (colourless) media. The first colour is the default variant's, because the frontend preselects colors[0]
      and its first size.
    - otherwise sizes only: `sizes`, `colors` is empty, `media_files` is all media.
    - neither: both empty (the single variant is the card's `variant_id`).
    A colourless variant of a product that has colours is not offered: the frontend can only show them by colour.
    """
    variants = product.active_variants  # already ordered default first
    media = list(product.media.all())
    shared_media = [item for item in media if item.color_id is None]

    by_color = {}
    for variant in variants:
        if variant.color_id is not None:
            by_color.setdefault(variant.color_id, []).append(variant)

    colors = []
    for color_variants in by_color.values():
        color = color_variants[0].color
        own_media = [item for item in media if item.color_id == color.pk]
        entry = {
            "name": color.name,
            "hex_code": color.hex_code,
            "media_files": _media_entries(own_media or shared_media, request),
            "sizes": _sorted_sizes(color_variants),
        }
        plain = next((v for v in color_variants if v.size_id is None), None)
        if plain is not None:
            base, final = pricing.variant_prices(plain)
            entry.update(
                variant_id=plain.pk, base_price=base, discount_price=final, availability_status=plain.stock_quantity > 0
            )
        colors.append(entry)

    sizes = [] if colors else _sorted_sizes(v for v in variants if v.color_id is None)
    return colors, sizes, _media_entries(shared_media if colors else media, request)


class ProductDetailSerializer(ProductListSerializer):
    """The card plus everything the detail page shows. `colors` / `sizes` are left out when they do not apply."""

    brand = serializers.SerializerMethodField()
    categories = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()
    tags = serializers.SerializerMethodField()
    thumbnail = serializers.SerializerMethodField()
    media_files = serializers.SerializerMethodField()
    dimension = serializers.SerializerMethodField()
    qrcode_image_url = serializers.SerializerMethodField()
    colors = OptionalMethodField()
    sizes = OptionalMethodField()

    class Meta(ProductListSerializer.Meta):
        fields = ProductListSerializer.Meta.fields + (
            "brand",
            "categories",
            "category",
            "tags",
            "thumbnail",
            "media_files",
            "minimum_order_quantity",
            "short_description",
            "long_description",
            "model",
            "weight",
            "dimension",
            "material",
            "features",
            "warranty_information",
            "shipping_information",
            "return_policy",
            "qrcode_image_url",
            "colors",
            "sizes",
        )
        read_only_fields = fields

    def to_representation(self, product):
        data = super().to_representation(product)
        for key in ("colors", "sizes"):
            if not data[key]:
                del data[key]  # the frontend tests `!product.colors`, so an empty list is not the same as absent
        return data

    def _options(self, product):
        cache = self.__dict__.setdefault("_options_cache", {})
        if product.pk not in cache:
            cache[product.pk] = build_options(product, self.context.get("request"))
        return cache[product.pk]

    @extend_schema_field(NameSerializer(allow_null=True))
    def get_brand(self, product):
        return {"name": product.brand.name} if product.brand_id else None

    @extend_schema_field(CategoryRefSerializer(many=True))
    def get_categories(self, product):
        return [{"name": category.name, "slug": category.slug} for category in product.visible_categories]

    @extend_schema_field(serializers.SlugField(allow_null=True, help_text="Slug of the primary category."))
    def get_category(self, product):
        primary = product.primary_category
        if primary is not None and primary.is_active:
            return primary.slug
        return product.visible_categories[0].slug if product.visible_categories else None

    @extend_schema_field(NameSerializer(many=True))
    def get_tags(self, product):
        return [{"name": tag.name} for tag in product.tags.all()]

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_thumbnail(self, product):
        return absolute_url(self.context.get("request"), product.main_thumbnail)

    @extend_schema_field(MediaFileSerializer(many=True))
    def get_media_files(self, product):
        return self._options(product)[2]

    @extend_schema_field(DimensionSerializer(allow_null=True))
    def get_dimension(self, product):
        values = (product.dimension_width, product.dimension_height, product.dimension_depth)
        if all(value is None for value in values):
            return None
        return dict(zip(("width", "height", "depth"), values))

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_qrcode_image_url(self, product):
        return absolute_url(self.context.get("request"), product.qrcode_image)

    @extend_schema_field(ColorOptionSerializer(many=True, required=False))
    def get_colors(self, product):
        return self._options(product)[0]

    @extend_schema_field(SizeOptionSerializer(many=True, required=False))
    def get_sizes(self, product):
        return self._options(product)[1]


# --- categories ---------------------------------------------------------------------------------------------


class CategoryListSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()
    has_discount = serializers.BooleanField(read_only=True)
    discount_type = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ("id", "name", "slug", "image", "has_discount", "discount_amount", "discount_type")
        read_only_fields = fields

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_image(self, category):
        return absolute_url(self.context.get("request"), category.image)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_discount_type(self, category):
        return category.discount_type or None
