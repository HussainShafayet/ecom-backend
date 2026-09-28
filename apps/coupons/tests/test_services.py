from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.catalog.models import DiscountType
from apps.coupons import services
from apps.coupons.models import Coupon
from apps.coupons.tests.helpers import make_coupon

pytestmark = pytest.mark.django_db

PHONE = "+8801712345678"


def rejects(coupon, subtotal="1000.00", phone_number=PHONE):
    with pytest.raises(ValidationError) as exc:
        services.validate_coupon(coupon.code, Decimal(subtotal), phone_number)
    return str(exc.value.detail[0])


# --- compute_discount -----------------------------------------------------------------------------------------
def test_percentage_discount():
    coupon = make_coupon(discount_type=DiscountType.PERCENTAGE, discount_value="25.00")
    assert services.compute_discount(coupon, Decimal("1000.00")) == Decimal("250.00")


def test_fixed_discount():
    coupon = make_coupon(discount_type=DiscountType.FIXED, discount_value="150.00")
    assert services.compute_discount(coupon, Decimal("1000.00")) == Decimal("150.00")


def test_discount_never_exceeds_the_subtotal():
    coupon = make_coupon(discount_type=DiscountType.FIXED, discount_value="150.00")
    assert services.compute_discount(coupon, Decimal("100.00")) == Decimal("100.00")


def test_max_discount_amount_caps_a_percentage_coupon():
    coupon = make_coupon(discount_type=DiscountType.PERCENTAGE, discount_value="50.00", max_discount_amount="300.00")
    assert services.compute_discount(coupon, Decimal("1000.00")) == Decimal("300.00")


# --- validate_coupon -------------------------------------------------------------------------------------------
def test_unknown_code_is_refused():
    with pytest.raises(ValidationError) as exc:
        services.validate_coupon("NOSUCHCODE", Decimal("1000.00"), PHONE)
    assert str(exc.value.detail[0]) == "This coupon code does not exist."


def test_an_inactive_coupon_is_refused():
    coupon = make_coupon(is_active=False)
    assert rejects(coupon) == "This coupon is no longer active."


def test_not_yet_valid_is_refused():
    coupon = make_coupon(valid_from=timezone.now() + timedelta(days=1))
    assert rejects(coupon) == "This coupon is not active yet."


def test_expired_is_refused():
    coupon = make_coupon(valid_until=timezone.now() - timedelta(days=1))
    assert rejects(coupon) == "This coupon has expired."


def test_below_the_minimum_order_amount_is_refused():
    coupon = make_coupon(min_order_amount="2000.00")
    assert rejects(coupon, subtotal="1000.00") == "This coupon needs an order of at least 2000.00."


def test_at_or_above_the_minimum_order_amount_is_accepted():
    coupon = make_coupon(min_order_amount="1000.00")
    services.validate_coupon(coupon.code, Decimal("1000.00"), PHONE)  # does not raise


def test_a_code_is_case_and_whitespace_insensitive():
    coupon = make_coupon(code="SUMMER25")
    assert services.validate_coupon(" summer25 ", Decimal("1000.00"), PHONE).pk == coupon.pk


def test_the_total_cap_is_enforced():
    coupon = make_coupon(max_redemptions=1, times_used=1)
    assert rejects(coupon) == "This coupon is no longer available."


def test_a_customer_at_their_own_cap_is_refused(django_capture_on_commit_callbacks):
    from apps.cart.tests.helpers import stocked
    from apps.orders.tests.helpers import line, make_order

    coupon = make_coupon(max_redemptions_per_customer=1)
    mug, _ = stocked("Mug", stock=10)
    with django_capture_on_commit_callbacks(execute=True):
        make_order(line(mug), phone_number=PHONE, coupon_code=coupon.code)

    assert rejects(coupon) == "You have already used this coupon."


def test_a_different_customer_is_not_affected_by_someone_elses_cap(django_capture_on_commit_callbacks):
    from apps.cart.tests.helpers import stocked
    from apps.orders.tests.helpers import line, make_order

    coupon = make_coupon(max_redemptions_per_customer=1)
    mug, _ = stocked("Mug", stock=10)
    with django_capture_on_commit_callbacks(execute=True):
        make_order(line(mug), phone_number=PHONE, coupon_code=coupon.code)

    services.validate_coupon(coupon.code, Decimal("1000.00"), "+8801700000002")  # does not raise


def test_a_cancelled_orders_use_does_not_count_towards_the_per_customer_cap(django_capture_on_commit_callbacks):
    from apps.cart.tests.helpers import stocked
    from apps.orders import services as order_services
    from apps.orders.models import Order
    from apps.orders.tests.helpers import line, make_order

    coupon = make_coupon(max_redemptions_per_customer=1)
    mug, _ = stocked("Mug", stock=10)
    with django_capture_on_commit_callbacks(execute=True):
        order = make_order(line(mug), phone_number=PHONE, coupon_code=coupon.code)
    order_services.change_status(order, Order.Status.CANCELLED)

    services.validate_coupon(coupon.code, Decimal("1000.00"), PHONE)  # does not raise: the cancelled use is freed


# --- apply_coupon_to_order / release_coupon_usage --------------------------------------------------------------
def test_apply_coupon_to_order_increments_times_used():
    coupon = make_coupon(discount_type=DiscountType.PERCENTAGE, discount_value="10.00")
    redeemed, discount = services.apply_coupon_to_order(coupon.code, Decimal("1000.00"), PHONE)
    assert discount == Decimal("100.00")
    coupon.refresh_from_db()
    assert coupon.times_used == 1
    assert redeemed.pk == coupon.pk


def test_apply_coupon_to_order_re_checks_eligibility():
    coupon = make_coupon(max_redemptions=1, times_used=1)
    with pytest.raises(ValidationError):
        services.apply_coupon_to_order(coupon.code, Decimal("1000.00"), PHONE)


def test_release_coupon_usage_decrements_but_never_below_zero():
    coupon = make_coupon(times_used=0)
    services.release_coupon_usage(coupon.pk)
    coupon.refresh_from_db()
    assert coupon.times_used == 0

    coupon.times_used = 3
    coupon.save(update_fields=["times_used"])
    services.release_coupon_usage(coupon.pk)
    coupon.refresh_from_db()
    assert coupon.times_used == 2


def test_release_coupon_usage_of_none_does_nothing():
    services.release_coupon_usage(None)  # does not raise
