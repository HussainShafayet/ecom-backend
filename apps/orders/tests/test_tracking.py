"""`GET /orders/track/?order_id=&phone_number=`: a guest follows an order with its number and phone number."""
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.tests.helpers import verified_user
from apps.orders import services
from apps.orders.models import Order
from apps.orders.tests.helpers import DEFAULT_PHONE, ORDERS, line, make_order, stocked

pytestmark = pytest.mark.django_db

TRACK = f"{ORDERS}track/"
NOT_FOUND = "No order matches these details."


def track(client, order_id, phone_number=DEFAULT_PHONE, **extra):
    return client.get(TRACK, {"order_id": order_id, "phone_number": phone_number}, **extra)


def test_a_guest_follows_an_order_with_its_number_and_phone(api_client):
    product, _ = stocked("Mug", base_price="500.00", stock=10)
    order = make_order(line(product, quantity=2))
    services.change_status(order, Order.Status.SHIPPED)

    response = track(api_client, order.number)

    assert response.status_code == 200
    data = response.json()["data"]
    assert (data["order_id"], data["status"], data["status_display"]) == (order.number, "shipped", "Shipped")
    assert [step["status"] for step in data["history"]] == ["pending", "shipped"]
    assert (data["subtotal"], data["delivery_charge"], data["total"]) == (1000.0, 60.0, 1060.0)
    assert [(item["product_name"], item["quantity"]) for item in data["items"]] == [("Mug", 2)]
    assert data["payment"]["status"] == "pending"


def test_nothing_about_who_it_is_for_or_where_it_goes_is_shown(api_client):
    product, _ = stocked()
    order = make_order(line(product), name="Rahim Uddin", email="rahim@example.com", shipping_address="House 12, Road 5")

    response = track(api_client, order.number)

    assert set(response.json()["data"]) == {
        "order_id", "status", "status_display", "created_at", "total", "items_count", "items", "subtotal",
        "delivery_charge", "payment", "history",
    }
    text = response.content.decode()
    for private in ("Rahim", "rahim@example.com", "House 12", DEFAULT_PHONE, "Gulshan"):
        assert private not in text


def test_the_order_number_may_be_typed_in_lower_case(api_client):
    product, _ = stocked()
    order = make_order(line(product))
    assert track(api_client, order.number.lower()).status_code == 200
    assert track(api_client, f"  {order.number} ").status_code == 200


def test_a_signed_in_customers_order_can_be_tracked_too(api_client):
    user = verified_user("+8801711111111")
    product, _ = stocked()
    order = make_order(line(product), user=user, phone_number="+8801711111111")
    assert track(api_client, order.number, "+8801711111111").status_code == 200


def test_a_stale_token_does_not_turn_the_lookup_into_a_401(api_client):
    """The frontend may send its (expired) token; who is asking does not matter here."""
    user = verified_user()
    token = AccessToken.for_user(user)
    token.set_exp(from_time=timezone.now() - timedelta(hours=2), lifetime=timedelta(minutes=15))
    product, _ = stocked()
    order = make_order(line(product))

    response = track(api_client, order.number, HTTP_AUTHORIZATION=f"Bearer {token}")

    assert response.status_code == 200


# --- the same 404 whatever was wrong ----------------------------------------------------------------------------
def test_a_wrong_phone_and_an_unknown_number_are_the_same_404(api_client):
    product, _ = stocked()
    order = make_order(line(product))

    wrong_phone = track(api_client, order.number, "+8801799999999")
    unknown = track(api_client, "GC-19990101-0001")

    assert (wrong_phone.status_code, unknown.status_code) == (404, 404)
    assert wrong_phone.content == unknown.content
    assert wrong_phone.json()["error"] == NOT_FOUND


def test_the_phone_of_another_order_does_not_open_this_one(api_client):
    product, _ = stocked(stock=10)
    mine = make_order(line(product), phone_number="+8801711111111")
    make_order(line(product), phone_number="+8801722222222")
    assert track(api_client, mine.number, "+8801722222222").status_code == 404


@pytest.mark.parametrize(
    "params",
    [{}, {"order_id": "GC-20260101-0001"}, {"phone_number": DEFAULT_PHONE}, {"order_id": "", "phone_number": DEFAULT_PHONE}, {"order_id": "GC-1", "phone_number": "01712345678"}],
)
def test_missing_or_malformed_input_is_a_400(api_client, params):
    response = api_client.get(TRACK, params)
    assert response.status_code == 400
    assert response.json()["success"] is False


def test_the_track_route_is_not_taken_for_an_order_number(api_client):
    """`orders/track/` must be found before `orders/<number>/`, or `track` would be an unknown order (a 401 here)."""
    assert api_client.get(TRACK).status_code == 400  # a lookup without its parameters


def test_the_route_works_without_the_trailing_slash_too(api_client):
    product, _ = stocked()
    order = make_order(line(product))
    response = api_client.get(f"{ORDERS}track", {"order_id": order.number, "phone_number": DEFAULT_PHONE})
    assert response.status_code == 200


# --- guessing is limited ------------------------------------------------------------------------------------------
def test_wrong_guesses_count_against_the_limit(api_client, monkeypatch):
    monkeypatch.setitem(ScopedRateThrottle.THROTTLE_RATES, "order_track", "3/min")
    product, _ = stocked()
    order = make_order(line(product))

    statuses = [track(api_client, order.number, f"+880179999999{n}").status_code for n in range(4)]

    assert statuses == [404, 404, 404, 429]
    assert track(api_client, order.number).status_code == 429  # even the right phone waits: no oracle after the limit
    assert track(api_client, order.number).headers["Retry-After"]
