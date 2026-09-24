from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import F

from apps.catalog import services
from apps.catalog.models import Brand, Category, Color, Product, ProductVariant, Size, Tag
from apps.catalog.tests.helpers import (
    make_brand,
    make_category,
    make_color,
    make_product,
    make_size,
    make_variant,
)

pytestmark = pytest.mark.django_db
D = Decimal


# --- slugs -----------------------------------------------------------------------------------------------


def test_slugs_are_generated_and_unique():
    first = make_product("Red Shirt")
    second = make_product("Red Shirt")
    assert (first.slug, second.slug) == ("red-shirt", "red-shirt-2")
    assert make_category("Men & Women").slug == "men-women"
    assert make_brand("Acme Co").slug == "acme-co"


def test_slug_is_kept_when_the_name_changes():
    product = make_product("Red Shirt")
    product.name = "Blue Shirt"
    product.save()
    assert Product.objects.get(pk=product.pk).slug == "red-shirt"


def test_slug_can_be_set_by_hand():
    assert make_product("Red Shirt", slug="custom-slug").slug == "custom-slug"


def test_a_bengali_only_name_still_gets_a_slug():
    slug = make_product("লাল শার্ট").slug
    assert slug.startswith("item-")


# --- categories, reference data -----------------------------------------------------------------------------


def test_category_can_not_be_its_own_ancestor():
    root = make_category("Men")
    child = make_category("Shirts", parent=root)
    root.parent = child
    with pytest.raises(ValidationError) as error:
        root.full_clean()
    assert "parent" in error.value.message_dict
    root.parent = root
    with pytest.raises(ValidationError):
        root.full_clean()


def test_category_with_children_can_not_be_deleted():
    root = make_category("Men")
    make_category("Shirts", parent=root)
    with pytest.raises(Exception, match="protected"):
        root.delete()


@pytest.mark.parametrize(
    ("model", "kwargs"),
    [
        (Brand, {}),
        (Tag, {}),
        (Color, {"hex_code": "#000000"}),
        (Size, {}),
    ],
)
def test_names_are_unique_ignoring_case(model, kwargs):
    model.objects.create(name="Nike", **kwargs)
    with pytest.raises(ValidationError):
        model(name="nike", **kwargs).full_clean()
    with pytest.raises(IntegrityError), transaction.atomic():
        model.objects.create(name="NIKE", **kwargs)


@pytest.mark.parametrize("bad", ["red", "#12", "#GGGGGG", "#1234567", "FF0000"])
def test_color_hex_code_must_look_like_a_hex_colour(bad):
    with pytest.raises(ValidationError) as error:
        Color(name="X", hex_code=bad).full_clean()
    assert "hex_code" in error.value.message_dict


@pytest.mark.parametrize("good", ["#F00", "#ff0000", "#D7C4A3"])
def test_color_hex_code_accepts_short_and_long_forms(good):
    Color(name="X", hex_code=good).full_clean()


def test_sizes_order_by_sort_order_not_alphabet():
    for name, order in [("XL", 4), ("S", 1), ("L", 3), ("M", 2)]:
        make_size(name, order)
    assert [size.name for size in Size.objects.all()] == ["S", "M", "L", "XL"]


def test_category_discount_is_only_a_badge():
    category = make_category(discount_type="percentage", discount_amount=D("10"))
    assert category.has_discount is True
    assert make_category("Plain").has_discount is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"discount_type": "percentage", "discount_amount": D("101")},
        {"discount_type": "", "discount_amount": D("5")},
        {"discount_type": "fixed", "discount_amount": D("-1")},
    ],
)
def test_category_discount_rules_hold_in_the_database(kwargs):
    with pytest.raises(IntegrityError), transaction.atomic():
        make_category(**kwargs)


# --- product rules ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"discount_type": "percentage", "discount_value": D("100.01")},
        {"discount_type": "fixed", "discount_value": D("1000.01")},  # base price is 1000
        {"discount_type": "", "discount_value": D("5")},
        {"discount_value": D("-1"), "discount_type": "fixed"},
        {"base_price": D("-1")},
        {"minimum_order_quantity": 0},
        {"avg_rating": D("5.01")},
    ],
)
def test_product_rules_hold_in_the_database(kwargs):
    with pytest.raises(IntegrityError), transaction.atomic():
        make_product(**kwargs)


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"discount_type": "percentage", "discount_value": D("101")}, "discount_value"),
        ({"discount_type": "fixed", "discount_value": D("1001")}, "discount_value"),
        ({"discount_type": "", "discount_value": D("5")}, "discount_type"),
    ],
)
def test_product_full_clean_reports_the_same_rules(kwargs, field):
    product = Product(name="X", sku="X-1", base_price=D("1000"), **kwargs)
    with pytest.raises(ValidationError) as error:
        product.full_clean()
    assert field in error.value.message_dict


def test_sku_is_unique():
    make_product(sku="A-1")
    with pytest.raises(IntegrityError), transaction.atomic():
        make_product("Other", sku="A-1")


def test_deleting_a_brand_in_use_is_blocked():
    brand = make_brand()
    make_product(brand=brand)
    with pytest.raises(Exception, match="protected"):
        brand.delete()


def test_descriptions_are_sanitized_on_save():
    product = make_product(
        short_description='<p onclick="x()">Hi</p><script>alert(1)</script>',
        long_description='<h2>Title</h2><a href="javascript:alert(1)">bad</a><iframe src="https://x.io"></iframe>',
    )
    product.refresh_from_db()
    assert product.short_description == "<p>Hi</p>"
    assert "javascript" not in product.long_description
    assert "iframe" not in product.long_description
    assert "<h2>Title</h2>" in product.long_description


def test_plain_text_fields_are_not_touched():
    product = make_product(features="Waterproof & light <3")
    product.refresh_from_db()
    assert product.features == "Waterproof & light <3"


def test_counters_are_not_editable_in_forms():
    for name in ("total_views", "total_orders", "total_reviews", "avg_rating", "qrcode_image"):
        assert Product._meta.get_field(name).editable is False


def test_primary_category_is_added_to_categories():
    men, shirts = make_category("Men"), make_category("Shirts")
    product = make_product(primary_category=shirts)
    product.categories.add(men)
    services.sync_primary_category(product)
    assert set(product.categories.all()) == {men, shirts}
    assert product.primary_category == shirts


def test_a_missing_primary_category_falls_back_to_the_first_category():
    zeta, alpha = make_category("Zeta"), make_category("Alpha")
    product = make_product()
    product.categories.add(zeta, alpha)
    services.sync_primary_category(product)
    product.refresh_from_db()
    assert product.primary_category == alpha


def test_a_product_without_categories_stays_without_a_primary_category():
    product = make_product()
    services.sync_primary_category(product)
    assert product.primary_category is None


def test_deleting_the_primary_category_keeps_the_product():
    category = make_category()
    product = make_product(primary_category=category)
    category.delete()
    product.refresh_from_db()
    assert product.primary_category is None


# --- variants -----------------------------------------------------------------------------------------------


def test_first_variant_becomes_the_default():
    product = make_product()
    first, second = make_variant(product), make_variant(product, size=make_size())
    first.refresh_from_db()
    assert first.is_default is True
    assert second.is_default is False


def test_making_another_variant_the_default_moves_the_flag():
    product = make_product()
    first = make_variant(product)
    second = make_variant(product, size=make_size(), is_default=True)
    first.refresh_from_db()
    assert (first.is_default, second.is_default) == (False, True)
    assert product.variants.filter(is_default=True).count() == 1


def test_default_flags_of_different_products_do_not_interfere():
    a, b = make_variant(make_product("A")), make_variant(make_product("B"))
    assert a.is_default and b.is_default


def test_the_database_allows_only_one_default_per_product():
    product = make_product()
    make_variant(product)
    with pytest.raises(IntegrityError), transaction.atomic():
        ProductVariant.objects.bulk_create([ProductVariant(product=product, sku="dup-default", is_default=True)])


def test_two_plain_variants_of_one_product_are_refused_even_though_colour_and_size_are_null():
    product = make_product()
    make_variant(product)
    with pytest.raises(IntegrityError), transaction.atomic():
        make_variant(product)


def test_duplicate_colour_size_pair_is_refused_and_reported_by_full_clean():
    product, color, size = make_product(), make_color(), make_size()
    make_variant(product, color, size)
    duplicate = ProductVariant(product=product, color=color, size=size, sku="other")
    with pytest.raises(ValidationError):
        duplicate.full_clean()
    plain_duplicate = ProductVariant(product=make_variant(make_product("B")).product, sku="other-2")
    with pytest.raises(ValidationError):
        plain_duplicate.full_clean()


def test_the_same_colour_size_pair_is_fine_on_another_product():
    color, size = make_color(), make_size()
    make_variant(make_product("A"), color, size)
    make_variant(make_product("B"), color, size)


def test_sku_is_derived_from_product_colour_and_size():
    product = make_product(sku="tee-1")
    variant = make_variant(product, make_color("Sky Blue", "#00AAFF"), make_size("XL", 4))
    assert variant.sku == "TEE-1-SKY-BLUE-XL"
    assert make_variant(product).sku == "TEE-1"


def test_derived_sku_collisions_get_a_counter():
    make_variant(make_product("A", sku="X"), size=make_size("M"))  # derives X-M
    variant = make_variant(make_product("B", sku="X-M"))  # would also derive X-M
    assert variant.sku == "X-M-2"


def test_an_explicit_sku_is_kept():
    assert make_variant(make_product(), sku="MY-SKU").sku == "MY-SKU"


def test_variant_label():
    product = make_product()
    assert make_variant(product).label == "Default"
    assert make_variant(product, make_color(), make_size()).label == "Red / M"
    assert make_variant(product, make_color("Blue", "#0000FF")).label == "Blue"
    assert make_variant(product, size=make_size("L", 3)).label == "L"


def test_stock_can_not_go_negative():
    variant = make_variant(make_product(), stock_quantity=1)
    ProductVariant.objects.filter(pk=variant.pk).update(stock_quantity=F("stock_quantity") - 1)  # to 0: fine
    with pytest.raises(IntegrityError), transaction.atomic():
        ProductVariant.objects.filter(pk=variant.pk).update(stock_quantity=F("stock_quantity") - 1)


def test_variant_discount_price_can_not_exceed_its_base_price():
    with pytest.raises(IntegrityError), transaction.atomic():
        make_variant(make_product(), base_price=D("100"), discount_price=D("101"))


def test_variant_discount_price_is_checked_against_the_product_price_when_it_has_no_base_price():
    variant = ProductVariant(product=make_product(base_price="1000"), discount_price=D("1001"))
    with pytest.raises(ValidationError) as error:
        variant.full_clean()
    assert "discount_price" in error.value.message_dict


def test_deleting_a_colour_or_size_in_use_is_blocked():
    color, size = make_color(), make_size()
    make_variant(make_product(), color, size)
    with pytest.raises(Exception, match="protected"):
        color.delete()
    with pytest.raises(Exception, match="protected"):
        size.delete()


def test_deleting_a_product_deletes_its_variants():
    product = make_product()
    make_variant(product)
    product.delete()
    assert ProductVariant.objects.count() == 0
