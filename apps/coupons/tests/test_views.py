import pytest
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle

from apps.catalog.models import DiscountType
from apps.coupons.tests.helpers import VALIDATE, make_coupon

pytestmark = pytest.mark.django_db


def validate(client, **body):
    return client.post(VALIDATE, body, format="json")


def test_a_guest_can_preview_a_valid_coupon():
    coupon = make_coupon(discount_type=DiscountType.PERCENTAGE, discount_value="20.00")
    response = validate(APIClient(), code=coupon.code, subtotal="1000.00")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"] == {"discount_amount": 200.0, "total": 800.0}


def test_previewing_does_not_count_as_a_use():
    coupon = make_coupon()
    validate(APIClient(), code=coupon.code, subtotal="1000.00")
    coupon.refresh_from_db()
    assert coupon.times_used == 0


def test_an_unknown_code_is_a_400():
    response = validate(APIClient(), code="NOSUCHCODE", subtotal="1000.00")
    assert response.status_code == 400
    body = response.json()
    assert body["success"] is False
    assert body["errors"] == ["This coupon code does not exist."]


def test_a_missing_subtotal_is_a_400():
    response = validate(APIClient(), code="ANYTHING")
    assert response.status_code == 400


def test_the_coupon_rate_is_configured():
    number, seconds = ScopedRateThrottle().parse_rate(ScopedRateThrottle.THROTTLE_RATES["coupon"])
    assert number > 0 and seconds > 0


def test_it_is_throttled_per_client(monkeypatch):
    monkeypatch.setitem(ScopedRateThrottle.THROTTLE_RATES, "coupon", "1/min")
    client = APIClient()
    first = validate(client, code="NOSUCHCODE", subtotal="1000.00")
    second = validate(client, code="NOSUCHCODE", subtotal="1000.00")
    assert first.status_code == 400  # the bad code itself, not the throttle
    assert second.status_code == 429
