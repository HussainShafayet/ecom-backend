"""Real simultaneous requests for the last use of a limited coupon (same shape as orders' stock concurrency test)."""
import pytest
from rest_framework.test import APIClient

from apps.coupons.tests.helpers import make_coupon
from apps.orders.tests.helpers import errors_of, line, place, stocked
from apps.orders.tests.test_concurrency import run_together

pytestmark = pytest.mark.django_db(transaction=True)


def statuses(responses):
    return sorted(response.status_code for response in responses)


def test_two_orders_for_the_last_use_of_a_coupon_let_exactly_one_win():
    coupon = make_coupon(max_redemptions=1)
    products = [stocked(f"P{i}", stock=10)[0] for i in range(2)]  # separate products: only the coupon is contested

    responses = run_together(
        2, lambda index: place(APIClient(), line(products[index]), coupon_code=coupon.code)
    )

    assert statuses(responses) == [201, 400]
    loser = next(response for response in responses if response.status_code == 400)
    assert errors_of(loser) == ["This coupon is no longer available."]
    coupon.refresh_from_db()
    assert coupon.times_used == 1


def test_the_same_customer_racing_their_own_per_customer_cap_lets_exactly_one_win():
    coupon = make_coupon(max_redemptions_per_customer=1)
    products = [stocked(f"Q{i}", stock=10)[0] for i in range(2)]
    phone = "+8801799999999"

    responses = run_together(
        2,
        lambda index: place(APIClient(), line(products[index]), coupon_code=coupon.code, phone_number=phone),
    )

    assert statuses(responses) == [201, 400]
    coupon.refresh_from_db()
    assert coupon.times_used == 1
