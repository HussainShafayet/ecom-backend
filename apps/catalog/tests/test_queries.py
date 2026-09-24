from decimal import Decimal

import pytest

from apps.catalog import pricing
from apps.catalog.queries import descendant_category_ids, visible_products, with_list_fields
from apps.catalog.tests.helpers import (
    make_category,
    make_color,
    make_media,
    make_product,
    make_size,
    make_variant,
)

D = Decimal
pytestmark = pytest.mark.django_db


def annotated(product):
    return with_list_fields(visible_products().filter(pk=product.pk)).get()


# --- the SQL price is the Python price -----------------------------------------------------------------
PRICE_CASES = [
    # product discount, variant base_price, variant discount_price
    (("", "0"), None, None),
    (("percentage", "10"), None, None),
    (("percentage", "100"), None, None),
    (("fixed", "250"), None, None),
    (("fixed", "1000"), None, None),  # the whole price: free
    (("percentage", "10"), "1200.00", None),  # the discount applies to the variant's own base price
    (("fixed", "250"), "1200.00", None),
    (("", "0"), "1200.00", None),
    (("percentage", "10"), None, "800.00"),  # an explicit variant price beats the product's rule
    (("percentage", "10"), "1200.00", "1100.00"),
    (("", "0"), None, "999.00"),
]


@pytest.mark.parametrize(("discount", "variant_base", "variant_discount"), PRICE_CASES)
def test_sql_prices_equal_the_pricing_rules(discount, variant_base, variant_discount):
    product = make_product(base_price="1000.00", discount_type=discount[0], discount_value=discount[1])
    variant = make_variant(product, base_price=variant_base, discount_price=variant_discount)

    row = annotated(product)

    base, final = pricing.variant_prices(variant)
    assert (row.list_base_price, row.list_final_price) == (base, final)
    assert row.list_variant_id == variant.pk


@pytest.mark.parametrize(
    ("base", "percent", "expected"),
    [("999.99", "15", "849.99"), ("100.05", "50", "50.03"), ("0.05", "50", "0.03"), ("333.33", "33", "223.33")],
)
def test_percentage_rounds_half_up_like_the_python_rule(base, percent, expected):
    product = make_product(base_price=base, discount_type="percentage", discount_value=percent)
    make_variant(product)
    assert annotated(product).list_final_price == D(expected)
    assert pricing.product_prices(product)[1] == D(expected)


def test_product_without_variants_uses_the_product_price():
    product = make_product(base_price="500.00", discount_type="fixed", discount_value="50")
    row = annotated(product)
    assert (row.list_base_price, row.list_final_price) == (D("500.00"), D("450.00"))
    assert row.list_variant_id is None
    assert row.is_available is False
    assert row.has_options is False


# --- which variant the card stands for ------------------------------------------------------------------
def test_the_default_variant_is_used_and_an_inactive_one_is_skipped():
    product = make_product(base_price="1000.00")
    red, blue = make_color("Red", "#FF0000"), make_color("Blue", "#0000FF")
    first = make_variant(product, color=red, base_price="1100.00")  # becomes the default
    second = make_variant(product, color=blue, base_price="1300.00")
    assert annotated(product).list_variant_id == first.pk

    first.is_active = False
    first.save()
    row = annotated(product)
    assert row.list_variant_id == second.pk
    assert row.list_base_price == D("1300.00")


def test_availability_needs_an_active_variant_with_stock():
    product = make_product()
    red, blue = make_color("Red", "#FF0000"), make_color("Blue", "#0000FF")
    make_variant(product, color=red, stock_quantity=0)
    inactive = make_variant(product, color=blue, stock_quantity=5, is_active=False)
    assert annotated(product).is_available is False

    inactive.is_active = True
    inactive.save()
    assert annotated(product).is_available is True


def test_has_options_only_when_a_colour_or_size_is_chosen():
    plain = make_product()
    make_variant(plain)
    sized = make_product()
    make_variant(sized, size=make_size("M"))
    assert annotated(plain).has_options is False
    assert annotated(sized).has_options is True


# --- the main image -----------------------------------------------------------------------------------
def test_main_image_prefers_shared_images_then_the_admins_order():
    product = make_product()
    red = make_color("Red", "#FF0000")
    make_media(product, color=red, order=0)
    shared_late = make_media(product, order=5)
    shared_early = make_media(product, order=1)

    row = annotated(product)
    assert row.main_image == shared_early.file.name
    assert row.main_thumbnail == shared_early.thumbnail.name
    assert shared_late.file.name != row.main_image


def test_main_image_ignores_videos_and_can_be_missing():
    product = make_product()
    assert annotated(product).main_image is None
    make_media(product, video=True)
    assert annotated(product).main_image is None


# --- category subtree ---------------------------------------------------------------------------------
def test_descendants_include_the_category_itself_and_stop_at_hidden_ones():
    root = make_category("Clothing")
    shirts = make_category("Shirts", parent=root)
    polo = make_category("Polo", parent=shirts)
    hidden = make_category("Hidden", parent=root, is_active=False)
    make_category("Under hidden", parent=hidden)
    make_category("Shoes")

    assert set(descendant_category_ids(root.slug)) == {root.pk, shirts.pk, polo.pk}
    assert descendant_category_ids(polo.slug) == [polo.pk]
    assert descendant_category_ids(hidden.slug) == []
    assert descendant_category_ids("no-such-category") == []
