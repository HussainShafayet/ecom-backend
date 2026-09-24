"""`GET /products/` query parameters: one serializer validates them (and documents them in the OpenAPI schema),
`apply_product_filters` turns the validated values into a queryset."""
from django.db.models import Exists, OuterRef, Q
from rest_framework import serializers

from .models import DiscountType, Product, ProductVariant, Tag
from .queries import ORDERINGS, descendant_category_ids

MAX_NAMES = 50  # per comma separated parameter
MAX_SEARCH_WORDS = 6


class NamesField(serializers.CharField):
    """`a,b,c` -> ['a', 'b', 'c'] (trimmed, empty parts and case-insensitive repeats dropped)."""

    def to_internal_value(self, data):
        names = []
        for part in super().to_internal_value(data).split(","):
            part = part.strip()
            if part and part.lower() not in (name.lower() for name in names):
                names.append(part)
        if len(names) > MAX_NAMES:
            raise serializers.ValidationError(f"Give at most {MAX_NAMES} values.")
        return names


class ProductQuerySerializer(serializers.Serializer):
    category = serializers.CharField(
        required=False, allow_blank=True, help_text="Category slug. Includes the categories below it."
    )
    brands = NamesField(required=False, allow_blank=True, help_text="Comma separated brand names.")
    tags = NamesField(required=False, allow_blank=True, help_text="Comma separated tag names.")
    colors = NamesField(required=False, allow_blank=True, help_text="Comma separated colour names.")
    sizes = NamesField(required=False, allow_blank=True, help_text="Comma separated size names.")
    min_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=0, required=False, help_text="Lowest price the customer pays."
    )
    max_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=0, required=False, help_text="Highest price the customer pays."
    )
    discount_type = serializers.ChoiceField(choices=DiscountType.choices, required=False, allow_blank=True)
    discount_value = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0, required=False)
    search = serializers.CharField(
        required=False, allow_blank=True, max_length=100, help_text="Words that must all appear in the name, SKU, model, brand or a tag."
    )
    ordering = serializers.ChoiceField(
        choices=list(ORDERINGS),
        required=False,
        allow_blank=True,
        help_text="Empty = newest first. `price` sorts before the discount, `discount_price` by what the customer pays.",
    )


def parse_product_query(query_params):
    """Validated filter values from a request's query string. Blank values (`?min_price=`) count as absent and
    unknown keys (`page`, `page_size`, ...) are left to the paginator. Raises a 400 for a bad value."""
    serializer = ProductQuerySerializer(data={key: value for key, value in query_params.items() if value.strip()})
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def _any_name(field, names):
    """Case-insensitive `field IN names` as an OR of iexact."""
    condition = Q()
    for name in names:
        condition |= Q(**{f"{field}__iexact": name})
    return condition


def apply_product_filters(queryset, params):
    """Different parameters narrow the result (AND); several values of one parameter widen it (OR)."""
    slug = params.get("category")
    if slug:
        through = Product.categories.through
        ids = descendant_category_ids(slug)
        queryset = queryset.filter(
            Exists(through.objects.filter(product_id=OuterRef("pk"), category_id__in=ids))
        )

    if params.get("brands"):
        queryset = queryset.filter(_any_name("brand__name", params["brands"]))
    if params.get("tags"):
        tagged = Tag.objects.filter(products=OuterRef("pk")).filter(_any_name("name", params["tags"]))
        queryset = queryset.filter(Exists(tagged))

    if params.get("colors") or params.get("sizes"):
        # One variant has to match both (a red shirt in M, not a red one plus some M one).
        variants = ProductVariant.objects.filter(product=OuterRef("pk"), is_active=True)
        if params.get("colors"):
            variants = variants.filter(_any_name("color__name", params["colors"]))
        if params.get("sizes"):
            variants = variants.filter(_any_name("size__name", params["sizes"]))
        queryset = queryset.filter(Exists(variants))

    if "min_price" in params:
        queryset = queryset.filter(list_final_price__gte=params["min_price"])
    if "max_price" in params:
        queryset = queryset.filter(list_final_price__lte=params["max_price"])

    if params.get("discount_type"):
        queryset = queryset.filter(discount_type=params["discount_type"])
    if "discount_value" in params:
        queryset = queryset.filter(discount_value=params["discount_value"])

    for word in (params.get("search") or "").split()[:MAX_SEARCH_WORDS]:
        tagged = Tag.objects.filter(products=OuterRef("pk"), name__icontains=word)
        queryset = queryset.filter(
            Q(name__icontains=word)
            | Q(sku__icontains=word)
            | Q(model__icontains=word)
            | Q(brand__name__icontains=word)
            | Exists(tagged)
        )
    return queryset
