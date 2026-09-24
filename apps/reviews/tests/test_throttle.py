import pytest
from rest_framework.throttling import ScopedRateThrottle

from apps.reviews.tests.helpers import (
    REVIEWS,
    buyer,
    data,
    edit_review,
    other_customer,
    review_by,
    stocked,
    write_review,
)

pytestmark = pytest.mark.django_db


def test_the_review_rate_is_configured():
    number, seconds = ScopedRateThrottle().parse_rate(ScopedRateThrottle.THROTTLE_RATES["review"])
    assert number > 0 and seconds > 0


def test_writing_and_editing_share_one_allowance_per_customer(monkeypatch):
    monkeypatch.setitem(ScopedRateThrottle.THROTTLE_RATES, "review", "2/min")
    product, variant = stocked("Mug")
    _, client = buyer(product, variant)
    review_id = data(write_review(client, product))["id"]
    assert edit_review(client, review_id, rating=4).status_code == 200

    third = edit_review(client, review_id, rating=3)

    assert third.status_code == 429 and "Retry-After" in third
    assert third.json()["success"] is False


def test_reading_is_never_throttled(monkeypatch, api_client):
    monkeypatch.setitem(ScopedRateThrottle.THROTTLE_RATES, "review", "1/min")
    product, _ = stocked("Mug")
    review_by(other_customer(1), product)
    assert [api_client.get(REVIEWS, {"product_id": product.pk}).status_code for _ in range(5)] == [200] * 5


def test_each_customer_has_their_own_allowance(monkeypatch):
    monkeypatch.setitem(ScopedRateThrottle.THROTTLE_RATES, "review", "1/min")
    product, variant = stocked("Mug", stock=5)
    _, first = buyer(product, variant, "+8801711111111")
    _, second = buyer(product, variant, "+8801722222222")

    assert write_review(first, product).status_code == 201
    assert write_review(first, product).status_code == 429  # counted before the checks: no probing for free
    assert write_review(second, product).status_code == 201  # not held up by the first customer (same address)


def test_a_guest_is_refused_before_anything_is_counted_or_read(monkeypatch, api_client):
    monkeypatch.setitem(ScopedRateThrottle.THROTTLE_RATES, "review", "1/min")
    product, _ = stocked("Mug")
    assert write_review(api_client, product).status_code == 401
    assert write_review(api_client, product).status_code == 401  # 401, not 429: authentication comes first


def test_reading_reviews_is_held_to_the_default_limits_too():
    """The review list is public; its `get_throttles` used to return nothing for a read."""
    from types import SimpleNamespace

    from apps.reviews.views import ReviewListCreateView

    view = ReviewListCreateView()
    view.request = SimpleNamespace(method="GET")
    assert [type(throttle).__name__ for throttle in view.get_throttles()] == ["AnonRateThrottle", "UserRateThrottle"]
    view.request = SimpleNamespace(method="POST")
    assert [type(throttle).__name__ for throttle in view.get_throttles()] == ["ScopedRateThrottle"]
