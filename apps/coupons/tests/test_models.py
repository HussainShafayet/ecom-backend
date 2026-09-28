from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.catalog.models import DiscountType
from apps.coupons.models import Coupon
from apps.coupons.tests.helpers import make_coupon

pytestmark = pytest.mark.django_db


def test_the_code_is_stored_upper_case():
    coupon = make_coupon(code="summer25")
    assert coupon.code == "SUMMER25"


def test_a_zero_discount_value_is_refused():
    with pytest.raises(IntegrityError), transaction.atomic():
        make_coupon(discount_value="0.00")


def test_a_percentage_over_100_is_refused():
    with pytest.raises(IntegrityError), transaction.atomic():
        make_coupon(discount_type=DiscountType.PERCENTAGE, discount_value="150.00")


def test_a_fixed_discount_over_100_is_fine():
    coupon = make_coupon(discount_type=DiscountType.FIXED, discount_value="500.00")
    coupon.refresh_from_db()
    assert coupon.discount_value == 500


def test_valid_until_before_valid_from_is_refused():
    now = timezone.now()
    with pytest.raises(IntegrityError), transaction.atomic():
        make_coupon(valid_from=now, valid_until=now - timedelta(days=1))


def test_a_negative_min_order_amount_is_refused():
    with pytest.raises(IntegrityError), transaction.atomic():
        make_coupon(min_order_amount="-10.00")


def test_default_max_redemptions_is_unlimited():
    coupon = make_coupon()
    assert coupon.max_redemptions is None
    assert coupon.max_redemptions_per_customer is None
    assert coupon.times_used == 0
    assert coupon.is_active is True
