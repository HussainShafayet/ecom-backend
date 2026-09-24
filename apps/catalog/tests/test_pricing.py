from decimal import Decimal

import pytest

from apps.catalog import pricing
from apps.catalog.tests.helpers import make_product, make_variant

D = Decimal


@pytest.mark.parametrize(
    ("base", "kind", "value", "expected"),
    [
        ("1000", "", "0", "1000.00"),  # no rule
        ("1000", "percentage", "0", "1000.00"),  # rule with a zero value
        ("1000", "percentage", "10", "900.00"),
        ("999.99", "percentage", "15", "849.99"),  # 849.9915 rounds down
        ("100.05", "percentage", "50", "50.03"),  # 50.025 rounds half up
        ("1000", "fixed", "250", "750.00"),
        ("100", "fixed", "150", "0.00"),  # never below zero
        ("100", "percentage", "100", "0.00"),
    ],
)
def test_apply_discount(base, kind, value, expected):
    assert pricing.apply_discount(D(base), kind, D(value)) == D(expected)


def test_unknown_discount_type_is_refused():
    with pytest.raises(ValueError):
        pricing.apply_discount(D("10"), "buy-one-get-one", D("1"))


def test_float_prices_are_refused():
    with pytest.raises(TypeError):
        pricing.apply_discount(10.5, "fixed", D("1"))


@pytest.mark.django_db
def test_product_prices_and_flags():
    plain = make_product("Plain")
    discounted = make_product("Sale", discount_type="percentage", discount_value=D("20"))
    assert pricing.product_prices(plain) == (D("1000.00"), D("1000.00"))
    assert plain.has_discount is False
    assert pricing.product_prices(discounted) == (D("1000.00"), D("800.00"))
    assert discounted.has_discount is True
    assert discounted.final_price == D("800.00")


@pytest.mark.django_db
def test_variant_inherits_the_product_price_and_discount():
    product = make_product(discount_type="fixed", discount_value=D("100"))
    variant = make_variant(product)
    assert pricing.variant_prices(variant) == (D("1000.00"), D("900.00"))


@pytest.mark.django_db
def test_variant_base_price_override_gets_the_product_discount():
    product = make_product(discount_type="percentage", discount_value=D("10"))
    variant = make_variant(product, base_price=D("1500"))
    assert pricing.variant_prices(variant) == (D("1500.00"), D("1350.00"))


@pytest.mark.django_db
def test_variant_discount_price_is_used_as_the_final_price():
    product = make_product(discount_type="percentage", discount_value=D("10"))
    variant = make_variant(product, base_price=D("1500"), discount_price=D("1200"))
    assert pricing.variant_prices(variant) == (D("1500.00"), D("1200.00"))


@pytest.mark.parametrize(
    ("variant_base", "discount", "product_base", "bad"),
    [
        (None, D("900"), D("1000"), False),
        (None, D("1000"), D("1000"), False),
        (None, D("1001"), D("1000"), True),
        (D("500"), D("600"), D("1000"), True),  # measured against the variant's own base price
        (D("500"), None, D("1000"), False),
    ],
)
def test_discount_price_error(variant_base, discount, product_base, bad):
    assert bool(pricing.discount_price_error(variant_base, discount, product_base)) is bad
