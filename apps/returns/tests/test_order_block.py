"""The `returns` block of `GET /orders/{order_id}/`, and the item `id` it works with."""
import pytest

from apps.orders import hooks
from apps.orders.models import Order
from apps.orders.tests.helpers import ORDERS, line, make_order, signed_in, stocked
from apps.returns.models import ReturnRequest, ReturnSettings

from .helpers import body, delivered_order, returns_url

pytestmark = pytest.mark.django_db


def detail(client, order):
    return client.get(f"{ORDERS}{order.number}/").json()["data"]


def test_a_delivered_order_says_what_may_be_returned_and_until_when():
    me, client = signed_in()
    mug, _ = stocked()
    order = delivered_order(me, line(mug, quantity=2))

    returns = detail(client, order)["returns"]

    assert returns["can_request"] is True
    assert returns["message"] is None
    assert returns["until"]
    assert returns["items"] == [{"item_id": order.items.get().pk, "quantity": 2}]
    assert returns["requests"] == []
    assert {reason["value"] for reason in returns["reasons"]} == set(ReturnRequest.Reason.values)
    assert all(reason["label"] for reason in returns["reasons"])


def test_the_block_says_what_returning_costs_and_which_reasons_are_free():
    me, client = signed_in()
    mug, _ = stocked()
    order = delivered_order(me, line(mug))

    returns = detail(client, order)["returns"]

    assert returns["return_charge"] == 60.0  # the order's own delivery charge
    free = {reason["value"]: reason["free"] for reason in returns["reasons"]}
    assert free == {"damaged": True, "wrong_item": True, "not_as_described": True, "size_fit": False, "changed_mind": False, "other": False}


def test_when_the_shop_charges_nothing_for_returns_the_block_says_every_reason_is_free():
    me, client = signed_in()
    mug, _ = stocked()
    order = delivered_order(me, line(mug))
    ReturnSettings.load()
    ReturnSettings.objects.update(charge_return_delivery=False)

    returns = detail(client, order)["returns"]

    assert returns["return_charge"] == 0
    assert all(reason["free"] for reason in returns["reasons"])


def test_a_request_shows_its_goods_charge_and_refund_but_never_what_the_courier_costs_the_shop():
    me, client = signed_in()
    mug, _ = stocked("Mug", base_price="200.00")
    order = delivered_order(me, line(mug, quantity=2))
    client.post(returns_url(order), body(order, (0, 2), reason="changed_mind"), format="json")

    [request] = detail(client, order)["returns"]["requests"]

    assert (request["goods_amount"], request["return_charge"], request["refund_amount"]) == (400.0, 60.0, 340.0)
    assert "courier_cost" not in request and "shop_cost" not in request
    assert "good_quantity" not in request["items"][0] and "damaged_quantity" not in request["items"][0]


def test_the_items_of_an_order_carry_the_id_a_request_names():
    me, client = signed_in()
    mug, _ = stocked()
    order = make_order(line(mug), user=me)
    [item] = detail(client, order)["items"]
    assert item["id"] == order.items.get().pk


def test_an_order_that_is_not_delivered_offers_nothing_and_says_nothing():
    me, client = signed_in()
    mug, _ = stocked()
    order = make_order(line(mug), user=me)

    returns = detail(client, order)["returns"]

    assert (returns["can_request"], returns["message"], returns["until"], returns["items"]) == (False, None, None, [])


def test_a_closed_window_is_explained():
    me, client = signed_in()
    mug, _ = stocked()
    order = delivered_order(me, line(mug), days_ago=30)

    returns = detail(client, order)["returns"]

    assert returns["can_request"] is False
    assert returns["message"].startswith("The time to return this order ended on ")
    assert returns["items"] == []


def test_switching_returns_off_is_explained_and_shows_no_last_day():
    me, client = signed_in()
    mug, _ = stocked()
    order = delivered_order(me, line(mug))
    ReturnSettings.load()
    ReturnSettings.objects.update(enabled=False)

    returns = detail(client, order)["returns"]

    assert (returns["can_request"], returns["until"]) == (False, None)
    assert returns["message"] == "The shop is not taking return requests right now."


def test_the_requests_are_listed_newest_first_with_their_lines_and_the_shops_answer():
    me, client = signed_in()
    mug, _ = stocked("Mug", base_price="200.00")
    order = delivered_order(me, line(mug, quantity=4))
    client.post(returns_url(order), body(order, (0, 1)), format="json")
    client.post(returns_url(order), body(order, (0, 2), reason="wrong_item"), format="json")
    ReturnRequest.objects.filter(reason="damaged").update(status="rejected", response="Used")

    requests = detail(client, order)["returns"]["requests"]

    assert [(r["reason"], r["status"], r["response"]) for r in requests] == [("wrong_item", "requested", ""), ("damaged", "rejected", "Used")]
    assert requests[0]["status_display"] == "Requested" and requests[0]["reason_display"] == "I got the wrong item"
    assert requests[0]["items"] == [{"item_id": order.items.get().pk, "product_name": "Mug", "variant_label": "Default", "unit_price": 200.0, "quantity": 2}]


def test_the_list_of_orders_and_the_guests_tracking_have_no_returns_block():
    me, client = signed_in()
    mug, _ = stocked()
    order = delivered_order(me, line(mug))

    listed = client.get(ORDERS).json()["data"]["results"][0]
    tracked = client.get(f"{ORDERS}track/", {"order_id": order.number, "phone_number": order.phone_number}).json()["data"]

    assert "returns" not in listed and "returns" not in tracked


def test_without_the_returns_app_the_block_is_null(monkeypatch):
    monkeypatch.setattr(hooks, "_returns_providers", [])
    me, client = signed_in()
    mug, _ = stocked()
    order = make_order(line(mug), user=me)
    assert detail(client, order)["returns"] is None
    assert Order.objects.count() == 1


def test_reading_an_order_costs_the_same_few_queries_however_many_requests_it_has(django_assert_max_num_queries):
    me, client = signed_in()
    mug, _ = stocked(stock=50)
    order = delivered_order(me, line(mug, quantity=20))
    for _ in range(5):
        client.post(returns_url(order), body(order, (0, 1)), format="json")
    with django_assert_max_num_queries(25):
        assert client.get(f"{ORDERS}{order.number}/").status_code == 200
