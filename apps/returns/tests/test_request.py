"""`POST /orders/{order_id}/returns/` and `POST /orders/{order_id}/returns/{id}/cancel/`: the customer asks to send
delivered goods back, or changes their mind."""
from decimal import Decimal

import pytest
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle

from apps.coupons.tests.helpers import make_coupon
from apps.orders import services as order_services
from apps.orders.models import DeliveryCharge, Order
from apps.orders.tests.helpers import errors_of, line, make_order, signed_in, stocked
from apps.orders.tests.test_concurrency import run_together
from apps.returns.models import ReturnRequest, ReturnSettings

from .helpers import body, cancel_url, delivered_order, returns_url

pytestmark = pytest.mark.django_db


def two_line_order(me):
    mug, _ = stocked("Mug", stock=10, base_price="500.00")
    shirt, _ = stocked("Shirt", stock=10, base_price="300.00")
    return delivered_order(me, line(mug, quantity=3), line(shirt, quantity=1))


# --- the happy path ---------------------------------------------------------------------------------------------
def test_a_customer_asks_to_return_part_of_a_delivered_order():
    me, client = signed_in()
    order = two_line_order(me)

    response = client.post(returns_url(order), body(order, (0, 2), reason="size_fit", details="Too big"), format="json")

    assert response.status_code == 201
    payload = response.json()
    assert (payload["success"], payload["message"]) == (True, "Return requested.")
    returns = payload["data"]["returns"]
    [created] = returns["requests"]
    assert (created["status"], created["reason"], created["details"], created["response"]) == ("requested", "size_fit", "Too big", "")
    assert (created["goods_amount"], created["return_charge"], created["refund_amount"]) == (1000.0, 60.0, 940.0)  # two mugs at 500, less the 60 delivery
    assert [(item["product_name"], item["quantity"], item["unit_price"]) for item in created["items"]] == [("Mug", 2, 500.0)]
    assert payload["data"]["status"] == "delivered"  # the order itself does not change
    stored = ReturnRequest.objects.get()
    assert (stored.order, stored.status) == (order, "requested")


def test_the_units_that_are_asked_for_are_no_longer_free_to_return():
    me, client = signed_in()
    order = two_line_order(me)
    client.post(returns_url(order), body(order, (0, 2)), format="json")

    returns = client.get(f"/api/v1/orders/{order.number}/").json()["data"]["returns"]

    free = {item["item_id"]: item["quantity"] for item in returns["items"]}
    mug_id, shirt_id = [item.pk for item in order.items.all()]
    assert free == {mug_id: 1, shirt_id: 1}
    assert returns["can_request"] is True


def test_a_coupon_is_taken_off_the_refund_in_proportion():
    me, client = signed_in()
    coupon = make_coupon(discount_value="10.00")  # 10% off everything
    mug, _ = stocked("Mug", stock=10, base_price="500.00")
    order = delivered_order(me, line(mug, quantity=2), coupon_code=coupon.code)

    created = client.post(returns_url(order), body(order, (0, 1)), format="json").json()["data"]["returns"]["requests"][0]

    assert created["refund_amount"] == 450.0  # 500 less its 10% share of the coupon


def test_a_whole_order_can_be_asked_for_and_then_nothing_is_left():
    me, client = signed_in()
    order = two_line_order(me)

    data = client.post(returns_url(order), body(order, (0, 3), (1, 1)), format="json").json()["data"]

    assert data["returns"]["can_request"] is False
    assert data["returns"]["items"] == []
    assert data["returns"]["message"] == "Everything in this order is already in a return request."
    again = client.post(returns_url(order), body(order, (0, 1)), format="json")
    assert errors_of(again) == ["Everything in this order is already in a return request."]


def test_the_route_works_without_the_trailing_slash_too():
    me, client = signed_in()
    order = two_line_order(me)
    assert client.post(returns_url(order).rstrip("/"), body(order, (0, 1)), format="json").status_code == 201


# --- what sending it back costs ----------------------------------------------------------------------------------
@pytest.mark.parametrize("reason", ["damaged", "wrong_item", "not_as_described"])
def test_a_return_for_a_fault_of_the_shop_is_free_and_the_shop_pays_the_courier(reason):
    me, client = signed_in()
    order = two_line_order(me)  # delivery 60

    created = client.post(returns_url(order), body(order, (0, 1), reason=reason), format="json").json()["data"]["returns"]["requests"][0]

    assert (created["goods_amount"], created["return_charge"], created["refund_amount"]) == (500.0, 0.0, 500.0)
    stored = ReturnRequest.objects.get()
    assert (stored.courier_cost, stored.return_charge, stored.shop_cost) == (60, 0, 60)  # the whole courier cost is the shop's


@pytest.mark.parametrize("reason", ["size_fit", "changed_mind"])
def test_a_return_for_the_customers_own_reason_costs_the_delivery_charge_taken_off_the_refund(reason):
    me, client = signed_in()
    order = two_line_order(me)

    created = client.post(returns_url(order), body(order, (0, 1), reason=reason), format="json").json()["data"]["returns"]["requests"][0]

    assert (created["goods_amount"], created["return_charge"], created["refund_amount"]) == (500.0, 60.0, 440.0)
    stored = ReturnRequest.objects.get()
    assert (stored.courier_cost, stored.return_charge, stored.shop_cost) == (60, 60, 0)  # the customer pays the courier


def test_the_reason_other_is_the_customers_own_too():
    me, client = signed_in()
    order = two_line_order(me)
    created = client.post(returns_url(order), body(order, (0, 1), reason="other", details="Not for me"), format="json").json()["data"]["returns"]["requests"][0]
    assert created["return_charge"] == 60.0


def test_the_charge_comes_off_the_goods_with_a_coupon_share_but_never_below_nothing():
    me, client = signed_in()
    coupon = make_coupon(discount_value="10.00")
    mug, _ = stocked("Mug", stock=10, base_price="30.00")  # one mug is worth 27 after the coupon, less than the 60 delivery
    order = delivered_order(me, line(mug, quantity=2), coupon_code=coupon.code)

    created = client.post(returns_url(order), body(order, (0, 1), reason="changed_mind"), format="json").json()["data"]["returns"]["requests"][0]

    assert (created["goods_amount"], created["return_charge"], created["refund_amount"]) == (27.0, 60.0, 0.0)


def test_when_the_shop_charges_nothing_for_returns_every_reason_is_free():
    me, client = signed_in()
    order = two_line_order(me)
    ReturnSettings.load()
    ReturnSettings.objects.update(charge_return_delivery=False)

    created = client.post(returns_url(order), body(order, (0, 1), reason="changed_mind"), format="json").json()["data"]["returns"]["requests"][0]

    assert (created["return_charge"], created["refund_amount"]) == (0.0, 500.0)
    assert ReturnRequest.objects.get().shop_cost == 60  # the shop pays the courier


def test_the_charge_is_fixed_when_the_request_is_made():
    me, client = signed_in()
    order = two_line_order(me)
    client.post(returns_url(order), body(order, (0, 1), reason="changed_mind"), format="json")

    DeliveryCharge.objects.update(amount=Decimal("200.00"))
    ReturnSettings.load()
    ReturnSettings.objects.update(charge_return_delivery=False)

    stored = ReturnRequest.objects.get()
    assert (stored.courier_cost, stored.return_charge) == (60, 60)  # an old request does not follow the new prices or policy


# --- when it is refused -----------------------------------------------------------------------------------------
@pytest.mark.parametrize("status", ["pending", "confirmed", "paid", "shipped", "cancelled"])
def test_an_order_that_is_not_delivered_can_not_be_returned(status):
    me, client = signed_in()
    mug, _ = stocked()
    order = make_order(line(mug), user=me)
    Order.objects.filter(pk=order.pk).update(status=status)

    response = client.post(returns_url(order), body(order, (0, 1)), format="json")

    assert errors_of(response) == ["Only a delivered order can be returned."]
    assert not ReturnRequest.objects.exists()


def test_the_return_window_is_counted_from_the_delivery():
    me, client = signed_in()
    mug, _ = stocked(stock=10)
    inside = delivered_order(me, line(mug), days_ago=7)  # the seventh day is still open
    outside = delivered_order(me, line(mug), days_ago=8)

    assert client.post(returns_url(inside), body(inside, (0, 1)), format="json").status_code == 201
    late = client.post(returns_url(outside), body(outside, (0, 1)), format="json")
    [sentence] = errors_of(late)
    assert sentence.startswith("The time to return this order ended on ")


def test_the_shop_can_change_the_window_and_switch_returns_off():
    me, client = signed_in()
    mug, _ = stocked(stock=10)
    order = delivered_order(me, line(mug, quantity=2), days_ago=20)
    assert client.post(returns_url(order), body(order, (0, 1)), format="json").status_code == 400

    ReturnSettings.load()
    ReturnSettings.objects.update(window_days=30)
    assert client.post(returns_url(order), body(order, (0, 1)), format="json").status_code == 201

    ReturnSettings.objects.update(enabled=False)
    refused = client.post(returns_url(order), body(order, (0, 1)), format="json")
    assert errors_of(refused) == ["The shop is not taking return requests right now."]


def test_more_units_than_are_free_is_refused_with_how_many_are_left():
    me, client = signed_in()
    order = two_line_order(me)
    client.post(returns_url(order), body(order, (0, 2)), format="json")

    response = client.post(returns_url(order), body(order, (0, 2), (1, 1)), format="json")

    assert errors_of(response) == ["Only 1 of Mug (Default) can still be returned."]
    assert ReturnRequest.objects.count() == 1  # nothing was written for the shirt either


def test_a_line_that_is_not_in_the_order_is_refused():
    me, client = signed_in()
    order = two_line_order(me)
    other = two_line_order(me)
    foreign = other.items.first()

    response = client.post(returns_url(order), {"reason": "damaged", "items": [{"item_id": foreign.pk, "quantity": 1}]}, format="json")

    assert errors_of(response) == ["One of those items is not in this order."]


def test_a_rejected_or_cancelled_request_lets_go_of_its_units():
    me, client = signed_in()
    order = two_line_order(me)
    first = client.post(returns_url(order), body(order, (0, 3)), format="json").json()["data"]["returns"]["requests"][0]
    assert client.post(returns_url(order), body(order, (0, 1)), format="json").status_code == 400  # all three are held

    order_returns = ReturnRequest.objects.get(pk=first["id"])
    from apps.returns import services

    services.change_status(order_returns, "rejected", response="No.")

    assert client.post(returns_url(order), body(order, (0, 3)), format="json").status_code == 201


@pytest.mark.parametrize(
    "payload, field",
    [
        ({"reason": "other", "items": "x"}, "items"),
        ({"reason": "nope"}, "reason"),
        ({"reason": "damaged", "items": []}, "items"),
        ({"reason": "damaged"}, "items"),
    ],
)
def test_a_malformed_body_is_a_400_naming_the_field(payload, field):
    me, client = signed_in()
    order = two_line_order(me)
    response = client.post(returns_url(order), payload, format="json")
    assert response.status_code == 400
    assert field in response.json()["field_errors"]


def test_the_reason_other_needs_a_few_words():
    me, client = signed_in()
    order = two_line_order(me)
    first = order.items.first()
    payload = {"reason": "other", "details": "   ", "items": [{"item_id": first.pk, "quantity": 1}]}

    response = client.post(returns_url(order), payload, format="json")

    assert response.status_code == 400
    assert response.json()["field_errors"]["details"] == ["Please tell us what is wrong."]
    payload["details"] = "It smells"
    assert client.post(returns_url(order), payload, format="json").status_code == 201


def test_the_same_line_twice_is_refused():
    me, client = signed_in()
    order = two_line_order(me)
    first = order.items.first()
    payload = {"reason": "damaged", "items": [{"item_id": first.pk, "quantity": 1}, {"item_id": first.pk, "quantity": 1}]}
    assert client.post(returns_url(order), payload, format="json").status_code == 400


def test_a_request_never_touches_the_stock_or_the_order():
    me, client = signed_in()
    mug, variant = stocked(stock=10)
    order = delivered_order(me, line(mug, variant, 2))
    stock = variant.__class__.objects.get(pk=variant.pk).stock_quantity

    client.post(returns_url(order), body(order, (0, 2)), format="json")

    assert variant.__class__.objects.get(pk=variant.pk).stock_quantity == stock
    assert Order.objects.get(pk=order.pk).status == "delivered"


# --- who may ---------------------------------------------------------------------------------------------------
def test_somebody_elses_order_a_guest_order_and_a_missing_one_are_all_a_404():
    me, client = signed_in()
    them, _ = signed_in("+8801812345678")
    mug, _ = stocked(stock=10)
    theirs = delivered_order(them, line(mug))
    guests = make_order(line(mug))
    order_services.change_status(guests, "shipped")
    order_services.change_status(guests, "delivered")

    responses = [
        client.post(returns_url(theirs), body(theirs, (0, 1)), format="json"),
        client.post(returns_url(guests), body(guests, (0, 1)), format="json"),
        client.post("/api/v1/orders/GC-19990101-0001/returns/", {"reason": "damaged", "items": [{"item_id": 1, "quantity": 1}]}, format="json"),
    ]

    assert [response.status_code for response in responses] == [404, 404, 404]
    assert not ReturnRequest.objects.exists()


def test_a_guest_can_not_ask():
    mug, _ = stocked()
    order = delivered_order(None, line(mug))
    assert APIClient().post(returns_url(order), body(order, (0, 1)), format="json").status_code == 401


def test_only_post_is_accepted():
    me, client = signed_in()
    order = two_line_order(me)
    assert client.get(returns_url(order)).status_code == 405


# --- cancelling a request --------------------------------------------------------------------------------------
def test_a_customer_cancels_a_request_nobody_has_answered():
    me, client = signed_in()
    order = two_line_order(me)
    created = client.post(returns_url(order), body(order, (0, 3)), format="json").json()["data"]["returns"]["requests"][0]

    response = client.post(cancel_url(order, created["id"]))

    assert response.status_code == 200
    payload = response.json()
    assert payload["message"] == "Return request cancelled."
    assert payload["data"]["returns"]["requests"][0]["status"] == "cancelled"
    assert payload["data"]["returns"]["can_request"] is True  # the units are free again


@pytest.mark.parametrize("status", ["approved", "rejected", "completed", "cancelled"])
def test_an_answered_request_can_not_be_cancelled_by_the_customer(status):
    me, client = signed_in()
    order = two_line_order(me)
    created = client.post(returns_url(order), body(order, (0, 1)), format="json").json()["data"]["returns"]["requests"][0]
    ReturnRequest.objects.filter(pk=created["id"]).update(status=status)

    response = client.post(cancel_url(order, created["id"]))

    assert errors_of(response) == ["Only a request the shop has not answered yet can be cancelled. Please contact us."]
    assert ReturnRequest.objects.get().status == status


def test_nobody_but_the_owner_can_cancel_a_request():
    me, client = signed_in()
    them, their_client = signed_in("+8801812345678")
    order = two_line_order(me)
    created = client.post(returns_url(order), body(order, (0, 1)), format="json").json()["data"]["returns"]["requests"][0]

    assert their_client.post(cancel_url(order, created["id"])).status_code == 404
    assert client.post(cancel_url(order, created["id"] + 99)).status_code == 404
    assert APIClient().post(cancel_url(order, created["id"])).status_code == 401
    assert ReturnRequest.objects.get().status == "requested"


# --- limits ----------------------------------------------------------------------------------------------------
def test_asking_shares_the_order_allowance(monkeypatch):
    monkeypatch.setitem(ScopedRateThrottle.THROTTLE_RATES, "order", "2/min")
    me, client = signed_in()
    order = two_line_order(me)

    statuses = [client.post(returns_url(order), body(order, (0, 1)), format="json").status_code for _ in range(3)]

    assert statuses == [201, 201, 429]


@pytest.mark.django_db(transaction=True)
def test_two_taps_at_once_ask_for_the_last_unit_only_once():
    me, client = signed_in()
    mug, _ = stocked(stock=10)
    order = delivered_order(me, line(mug, quantity=1))

    responses = run_together(2, lambda _: client.post(returns_url(order), body(order, (0, 1)), format="json"))

    assert sorted(response.status_code for response in responses) == [201, 400]
    assert ReturnRequest.objects.count() == 1
