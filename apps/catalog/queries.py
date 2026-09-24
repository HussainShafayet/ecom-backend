"""Read-side queries of the shop: what a customer may see, with prices and stock worked out in SQL.

A product card shows the price of the variant the shop would add to the cart: the default active variant
(`-is_default, id`). `with_list_fields` repeats `pricing.variant_prices` in SQL so that filtering and sorting by
price agree with the number on the card; `tests/test_queries.py` checks both against each other.
"""
from collections import defaultdict
from decimal import Decimal

from django.db.models import Case, DecimalField, Exists, F, OuterRef, Q, Subquery, Value, When
from django.db.models.functions import Coalesce, Greatest, Round

from .models import Category, DiscountType, Product, ProductMedia, ProductVariant

MONEY = DecimalField(max_digits=12, decimal_places=2)
HUNDRED = Value(Decimal("100"))
ZERO = Value(Decimal("0.00"), output_field=MONEY)

# `?ordering=` value -> order_by() fields. `price` sorts by the price before the discount, `discount_price` by
# the price the customer pays. Ties end in newest-first so pages never repeat or skip a product.
ORDERINGS = {
    "price": ("list_base_price",),
    "-price": ("-list_base_price",),
    "discount_price": ("list_final_price",),
    "-discount_price": ("-list_final_price",),
    "rating": ("avg_rating",),
    "-rating": ("-avg_rating",),
}
NEWEST_FIRST = ("-created_at", "-id")


def visible_products():
    return Product.objects.filter(is_active=True)


def _main_image_rows():
    """A product's images, best first (for a subquery on Product): shared (no colour) images first, then the admin's
    order. The first row is its main image."""
    return ProductMedia.objects.filter(product=OuterRef("pk"), file_type=ProductMedia.FileType.IMAGE).order_by(
        F("color").asc(nulls_first=True), "order", "id"
    )


def main_images(product_ids):
    """`{product_id: stored file name of its main image}` in one query; a product without an image is missing."""
    first_image = Subquery(_main_image_rows().values("file")[:1])
    rows = Product.objects.filter(pk__in=set(product_ids)).annotate(main_image=first_image)
    return {pk: name for pk, name in rows.values_list("pk", "main_image") if name}


def with_list_fields(queryset):
    """Annotate what a product card needs, so a whole page costs one query (plus one for the count)."""
    active_variants = ProductVariant.objects.filter(product=OuterRef("pk"), is_active=True)
    default_variant = active_variants.order_by("-is_default", "id")
    main_image = _main_image_rows()

    queryset = queryset.select_related("brand", "primary_category").annotate(
        list_variant_id=Subquery(default_variant.values("id")[:1]),
        variant_base=Subquery(default_variant.values("base_price")[:1], output_field=MONEY),
        variant_discount=Subquery(default_variant.values("discount_price")[:1], output_field=MONEY),
        is_available=Exists(active_variants.filter(stock_quantity__gt=0)),
        has_options=Exists(active_variants.filter(Q(color__isnull=False) | Q(size__isnull=False))),
        main_image=Subquery(main_image.values("file")[:1]),
        main_thumbnail=Subquery(main_image.values("thumbnail")[:1]),
    )
    queryset = queryset.annotate(list_base_price=Coalesce("variant_base", "base_price", output_field=MONEY))
    base = F("list_base_price")
    return queryset.annotate(
        list_final_price=Case(
            When(variant_discount__isnull=False, then=F("variant_discount")),
            When(
                discount_type=DiscountType.PERCENTAGE,
                discount_value__gt=0,
                then=Round(base - base * F("discount_value") / HUNDRED, 2),
            ),
            When(
                discount_type=DiscountType.FIXED,
                discount_value__gt=0,
                then=Greatest(base - F("discount_value"), ZERO),
            ),
            default=base,
            output_field=MONEY,
        )
    )


def order_products(queryset, ordering):
    return queryset.order_by(*ORDERINGS.get(ordering, ()), *NEWEST_FIRST)


def descendant_category_ids(slug):
    """Ids of the active category `slug` and of all its active descendants ([] when there is no such one).
    A hidden category hides its whole subtree."""
    rows = list(Category.objects.filter(is_active=True).values_list("id", "parent_id", "slug"))
    root_id = next((pk for pk, _, row_slug in rows if row_slug == slug), None)
    if root_id is None:
        return []
    children = defaultdict(list)
    for pk, parent_id, _ in rows:
        children[parent_id].append(pk)
    found, stack = [], [root_id]
    while stack:
        node = stack.pop()
        found.append(node)
        stack.extend(children.get(node, []))
    return found
