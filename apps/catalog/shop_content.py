"""`GET /content/shop/`: what the shop sidebar can filter by. Only values that a visible product actually
has are listed, so the customer never picks a filter that matches nothing."""
from collections import defaultdict

from django.db.models import Exists, Max, Min, OuterRef

from .models import Brand, Category, Color, ProductVariant, Size, Tag
from .queries import visible_products, with_list_fields


def category_tree():
    """Active categories as nested `{name, slug, children}`, roots first, each level A-Z."""
    rows = Category.objects.filter(is_active=True).order_by("name", "id").values("id", "parent_id", "name", "slug")
    children = defaultdict(list)
    for row in rows:
        children[row["parent_id"]].append(row)

    def build(parent_id):
        return [
            {"name": row["name"], "slug": row["slug"], "children": build(row["id"])}
            for row in children.get(parent_id, [])
        ]

    return build(None)


def _live_variants(**link):
    return ProductVariant.objects.filter(is_active=True, product__is_active=True, **link)


def shop_content():
    products = visible_products()
    prices = with_list_fields(products).aggregate(min_range=Min("list_final_price"), max_range=Max("list_final_price"))
    discounts = (
        products.filter(discount_value__gt=0)
        .exclude(discount_type="")
        .values("discount_type", "discount_value")
        .order_by("discount_type", "discount_value")
        .distinct()
    )
    return {
        "categories": category_tree(),
        "brands": list(
            Brand.objects.filter(Exists(products.filter(brand=OuterRef("pk")))).values_list("name", flat=True)
        ),
        "tags": list(Tag.objects.filter(Exists(products.filter(tags=OuterRef("pk")))).values_list("name", flat=True)),
        "colors": list(
            Color.objects.filter(Exists(_live_variants(color=OuterRef("pk")))).values("name", "hex_code")
        ),
        "sizes": list(Size.objects.filter(Exists(_live_variants(size=OuterRef("pk")))).values_list("name", flat=True)),
        "price_range": {
            "min_range": prices["min_range"] or 0,
            "max_range": prices["max_range"] or 0,
        },
        "discounts": [{"discount_type": row["discount_type"], "value": row["discount_value"]} for row in discounts],
    }
