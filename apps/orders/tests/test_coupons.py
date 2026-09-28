"""A coupon applied at checkout: `orders.services.place_order` redeems it, `change_status` gives it back on cancel."""
import pytest
from rest_framework.test import APIClient

from apps.coupons.tests.helpers import make_coupon
from apps.orders import services as order_services
from apps.orders.models import Order
from apps.orders.tests.helpers import errors_of, line, make_order, place, stocked

pytestmark = pytest.mark.django_db


def test_a_valid_coupon_discounts_the_order(django_capture_on_commit_callbacks):
    coupon = make_coupon(discount_value="10.00")  # 10% off, per make_coupon's default discount_type
    product, variant = stocked("Mug", stock=10, base_price="500.00")

    with django_capture_on_commit_callbacks(execute=True):
        response = place(APIClient(), line(product, variant, 2), coupon_code=coupon.code)

    assert response.status_code == 201
    body = response.json()["data"]
    assert body["subtotal"] == 1000.0
    assert body["discount_amount"] == 100.0
    assert body["total"] == 960.0  # 1000 - 100 + 60 delivery
    assert body["coupon_code"] == coupon.code

    order = Order.objects.get()
    assert order.coupon_id == coupon.pk
    assert order.discount_amount == 100
    coupon.refresh_from_db()
    assert coupon.times_used == 1


def test_no_coupon_means_no_discount():
    product, variant = stocked("Mug", stock=10, base_price="500.00")
    response = place(APIClient(), line(product, variant, 1))
    body = response.json()["data"]
    assert body["discount_amount"] == 0.0
    assert body["coupon_code"] == ""
    order = Order.objects.get()
    assert order.coupon_id is None


def test_an_unknown_coupon_code_is_one_more_sentence_in_errors():
    product, variant = stocked("Mug", stock=10)
    response = place(APIClient(), line(product, variant, 1), coupon_code="NOSUCHCODE")
    assert errors_of(response) == ["This coupon code does not exist."]
    assert Order.objects.count() == 0  # nothing written


def test_an_exhausted_coupon_refuses_the_order_and_writes_nothing():
    coupon = make_coupon(max_redemptions=1, times_used=1)
    product, variant = stocked("Mug", stock=10)
    response = place(APIClient(), line(product, variant, 1), coupon_code=coupon.code)
    assert errors_of(response) == ["This coupon is no longer available."]
    assert Order.objects.count() == 0
    coupon.refresh_from_db()
    assert coupon.times_used == 1  # unchanged


def test_cancelling_gives_the_coupons_use_back(django_capture_on_commit_callbacks):
    coupon = make_coupon()
    mug, _ = stocked("Mug", stock=10)
    with django_capture_on_commit_callbacks(execute=True):
        order = make_order(line(mug), coupon_code=coupon.code)
    coupon.refresh_from_db()
    assert coupon.times_used == 1

    order_services.change_status(order, Order.Status.CANCELLED)

    coupon.refresh_from_db()
    assert coupon.times_used == 0


def test_the_code_is_not_case_sensitive():
    coupon = make_coupon(code="SUMMER25")
    product, variant = stocked("Mug", stock=10)
    response = place(APIClient(), line(product, variant, 1), coupon_code="summer25")
    assert response.status_code == 201
    assert response.json()["data"]["coupon_code"] == "SUMMER25"
