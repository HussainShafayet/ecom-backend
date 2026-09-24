"""`POST /orders/{order_id}/cancel/`: the customer cancels their own pending order."""
import pytest
from rest_framework.throttling import ScopedRateThrottle

from apps.accounts.tests.helpers import verified_user
from apps.orders import services
from apps.orders.models import Order, OrderStatusHistory
from apps.orders.tests.helpers import ORDERS, line, make_order, orders_of, signed_in, stock_of, stocked
from apps.orders.tests.test_concurrency import run_together

pytestmark = pytest.mark.django_db


def cancel_url(order):
    return f"{ORDERS}{order.number}/cancel/"


# --- the happy path ---------------------------------------------------------------------------------------------
def test_a_customer_cancels_a_pending_order_and_the_goods_go_back_on_the_shelf():
    me, client = signed_in()
    product, variant = stocked("Mug", stock=10)
    order = make_order(line(product, variant, 3), user=me)
    assert (stock_of(variant), orders_of(product)) == (7, 1)

    response = client.post(cancel_url(order))

    assert response.status_code == 200
    body = response.json()
    assert (body["success"], body["message"]) == (True, "Order cancelled.")
    assert (body["data"]["order_id"], body["data"]["status"], body["data"]["can_cancel"]) == (order.number, "cancelled", False)
    assert body["data"]["payment"]["status"] == "cancelled"  # nothing was ever collected
    assert [step["status"] for step in body["data"]["history"]] == ["pending", "cancelled"]
    assert (stock_of(variant), orders_of(product)) == (10, 0)


def test_the_history_records_who_cancelled_and_why():
    me, client = signed_in()
    product, _ = stocked()
    order = make_order(line(product), user=me)

    client.post(cancel_url(order))

    last = OrderStatusHistory.objects.filter(order=order).last()
    assert (last.from_status, last.to_status, last.changed_by, last.note) == ("pending", "cancelled", me, "Cancelled by the customer.")


def test_the_route_works_without_the_trailing_slash_too():
    me, client = signed_in()
    product, _ = stocked()
    order = make_order(line(product), user=me)
    assert client.post(f"{ORDERS}{order.number}/cancel").status_code == 200


def test_the_customer_can_order_again_after_cancelling():
    me, client = signed_in()
    product, variant = stocked(stock=1)
    order = make_order(line(product), user=me)
    client.post(cancel_url(order))
    assert stock_of(variant) == 1
    make_order(line(product), user=me)  # the last unit is for sale again
    assert stock_of(variant) == 0


# --- what may not be cancelled ---------------------------------------------------------------------------------
@pytest.mark.parametrize("path", [["paid"], ["shipped"], ["shipped", "delivered"], ["cancelled"], ["paid", "refunded"]])
def test_an_order_that_is_no_longer_pending_is_a_400_and_stays_as_it_is(path):
    me, client = signed_in()
    product, variant = stocked(stock=10)
    order = make_order(line(product, variant, 2), user=me)
    for status in path:
        services.change_status(order, status)
    order.refresh_from_db()
    stock, history = stock_of(variant), OrderStatusHistory.objects.filter(order=order).count()

    response = client.post(cancel_url(order))

    assert response.status_code == 400
    assert response.json()["error"] == services.CANCEL_REFUSED
    order.refresh_from_db()
    assert order.status == path[-1]
    assert (stock_of(variant), OrderStatusHistory.objects.filter(order=order).count()) == (stock, history)


def test_cancelling_twice_is_a_400_the_second_time_and_restocks_once():
    me, client = signed_in()
    product, variant = stocked(stock=10)
    order = make_order(line(product, variant, 2), user=me)

    assert client.post(cancel_url(order)).status_code == 200
    assert client.post(cancel_url(order)).status_code == 400
    assert stock_of(variant) == 10


# --- whose order it is ------------------------------------------------------------------------------------------
def test_somebody_elses_order_a_guest_order_and_an_unknown_number_are_a_404_and_untouched():
    me, client = signed_in("+8801711111111")
    other = verified_user("+8801722222222")
    product, variant = stocked(stock=10)
    theirs, guests = make_order(line(product, variant), user=other), make_order(line(product, variant))

    responses = [client.post(cancel_url(theirs)), client.post(cancel_url(guests)), client.post(f"{ORDERS}GC-19990101-0001/cancel/")]

    assert [response.status_code for response in responses] == [404, 404, 404]
    assert set(Order.objects.values_list("status", flat=True)) == {"pending"}
    assert stock_of(variant) == 8


def test_a_guest_can_not_cancel(api_client):
    product, _ = stocked()
    order = make_order(line(product))
    assert api_client.post(cancel_url(order)).status_code == 401
    order.refresh_from_db()
    assert order.status == "pending"


def test_the_body_and_the_method_are_the_only_ways_in():
    me, client = signed_in()
    product, _ = stocked()
    order = make_order(line(product), user=me)
    assert client.get(cancel_url(order)).status_code == 405
    assert client.put(cancel_url(order), {}, format="json").status_code == 405


# --- limits --------------------------------------------------------------------------------------------------------
def test_cancelling_shares_the_order_allowance(monkeypatch):
    monkeypatch.setitem(ScopedRateThrottle.THROTTLE_RATES, "order", "2/min")
    me, client = signed_in()
    product, _ = stocked(stock=10)
    orders = [make_order(line(product), user=me) for _ in range(3)]

    statuses = [client.post(cancel_url(order)).status_code for order in orders]

    assert statuses == [200, 200, 429]
    assert client.post(cancel_url(orders[2])).headers["Retry-After"]


@pytest.mark.django_db(transaction=True)
def test_two_clicks_at_once_cancel_once_and_restock_once():
    me, client = signed_in()
    product, variant = stocked(stock=10)
    order = make_order(line(product, variant, 4), user=me)
    assert stock_of(variant) == 6

    responses = run_together(2, lambda _: client.post(cancel_url(order)))

    assert sorted(response.status_code for response in responses) == [200, 400]
    assert (stock_of(variant), orders_of(product)) == (10, 0)  # given back once, not twice
    assert OrderStatusHistory.objects.filter(order=order, to_status="cancelled").count() == 1
