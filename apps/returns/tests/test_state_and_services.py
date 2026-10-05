"""The return request flow (`state.py`) and what `services` does with it (the money and the status; the goods coming back are in test_receive.py)."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.orders.tests.helpers import line, signed_in, stocked
from apps.returns import services, state
from apps.returns.models import ReturnRequest, ReturnSettings

from .helpers import body, delivered_order, returns_url

pytestmark = pytest.mark.django_db

Status = ReturnRequest.Status


def make_request(*entries, reason="size_fit", **extra):
    """A request for the customer's own reason (a 60 delivery charge is the customer's): goods 500 per mug, charge 60."""
    me, client = signed_in()
    mug, _ = stocked("Mug", stock=10, base_price="500.00")
    order = delivered_order(me, line(mug, quantity=3), **extra)
    entries = entries or ((0, 1),)
    client.post(returns_url(order), body(order, *entries, reason=reason), format="json")
    return ReturnRequest.objects.get(order=order)


# --- the flow ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "old, new, allowed",
    [
        (Status.REQUESTED, Status.APPROVED, True),
        (Status.REQUESTED, Status.REJECTED, True),
        (Status.REQUESTED, Status.CANCELLED, True),
        (Status.REQUESTED, Status.RECEIVED, False),  # the goods can not arrive before the shop agreed
        (Status.REQUESTED, Status.COMPLETED, False),
        (Status.APPROVED, Status.RECEIVED, True),
        (Status.APPROVED, Status.CANCELLED, True),
        (Status.APPROVED, Status.COMPLETED, False),  # the money follows the goods
        (Status.APPROVED, Status.REJECTED, False),  # a promise is not taken back by refusing
        (Status.APPROVED, Status.REQUESTED, False),
        (Status.RECEIVED, Status.COMPLETED, True),
        (Status.RECEIVED, Status.CANCELLED, False),  # the stock has moved: there is no way back
        (Status.RECEIVED, Status.APPROVED, False),
        (Status.REJECTED, Status.APPROVED, False),
        (Status.COMPLETED, Status.CANCELLED, False),
        (Status.CANCELLED, Status.REQUESTED, False),
    ],
)
def test_the_flow_allows_only_the_listed_moves(old, new, allowed):
    assert state.can_transition(old, new) is allowed


def test_the_final_statuses_lead_nowhere_and_an_unknown_one_has_no_next():
    for status in (Status.REJECTED, Status.COMPLETED, Status.CANCELLED):
        assert state.allowed_next(status) == ()
    assert state.allowed_next("bogus") == ()


def test_every_status_has_a_row_in_the_flow():
    assert set(state.TRANSITIONS) == set(Status)


def test_requests_that_are_rejected_or_cancelled_are_the_only_ones_that_free_their_units():
    assert set(state.HOLDING) == {Status.REQUESTED, Status.APPROVED, Status.RECEIVED, Status.COMPLETED}


def test_the_money_is_locked_once_a_request_is_rejected_completed_or_cancelled():
    assert set(state.MONEY_LOCKED) == {Status.REJECTED, Status.COMPLETED, Status.CANCELLED}


# --- changing a status ------------------------------------------------------------------------------------------
def test_a_request_is_approved_received_and_completed_with_the_shops_words():
    request = make_request()

    services.change_status(request, Status.APPROVED, response="Send it to House 5.")
    services.receive_goods(request, [{"item_id": request.items.get().pk, "good": 1, "damaged": 0}])
    services.change_status(request, Status.COMPLETED)

    request.refresh_from_db()
    assert (request.status, request.response) == ("completed", "Send it to House 5.")  # no new words: the old ones stay
    assert request.received_at is not None and request.completed_at is not None
    assert request.received_at <= request.completed_at


def test_a_move_the_flow_does_not_allow_is_refused_and_changes_nothing():
    request = make_request()

    with pytest.raises(services.InvalidTransition) as refused:
        services.change_status(request, Status.COMPLETED, response="Done")

    assert str(refused.value.detail) == "A return request that is requested can not become completed."
    request.refresh_from_db()
    assert (request.status, request.response, request.completed_at) == ("requested", "", None)


def test_receiving_is_only_through_receive_goods():
    request = make_request()
    services.change_status(request, Status.APPROVED)
    with pytest.raises(ValueError):
        services.change_status(request, Status.RECEIVED)
    request.refresh_from_db()
    assert request.status == "approved"


def test_the_callers_copy_is_up_to_date_after_a_change():
    request = make_request()
    services.change_status(request, Status.REJECTED, response="No.")
    assert (request.status, request.response) == ("rejected", "No.")


def test_leaving_a_value_out_does_not_touch_it():
    request = make_request()
    services.staff_update(request, response="Hello")
    services.staff_update(request, status=Status.APPROVED)
    request.refresh_from_db()
    assert (request.status, request.response, request.return_charge, request.refund_amount) == ("approved", "Hello", 60, Decimal("440.00"))


# --- the money --------------------------------------------------------------------------------------------------
def test_waiving_the_charge_raises_the_refund_with_it_and_the_shop_pays_the_courier():
    request = make_request()  # goods 500, charge 60, refund 440
    assert (request.goods_amount, request.return_charge, request.refund_amount, request.shop_cost) == (500, 60, 440, 0)

    services.staff_update(request, return_charge=Decimal("0.00"))

    request.refresh_from_db()
    assert (request.return_charge, request.refund_amount, request.shop_cost) == (0, 500, 60)


def test_a_charge_that_is_set_again_moves_the_refund_and_a_refund_given_with_it_wins():
    request = make_request()
    services.staff_update(request, return_charge=Decimal("20.00"))
    request.refresh_from_db()
    assert request.refund_amount == Decimal("480.00")

    services.staff_update(request, return_charge=Decimal("30.00"), refund_amount=Decimal("400.00"))
    request.refresh_from_db()
    assert (request.return_charge, request.refund_amount) == (30, 400)


def test_the_refund_alone_can_be_changed_without_touching_the_charge():
    request = make_request()
    services.staff_update(request, refund_amount=Decimal("300.00"))
    request.refresh_from_db()
    assert (request.return_charge, request.refund_amount, request.goods_amount) == (60, 300, 500)


def test_the_refund_never_goes_below_nothing():
    request = make_request()
    services.staff_update(request, return_charge=Decimal("900.00"))
    request.refresh_from_db()
    assert (request.return_charge, request.refund_amount) == (900, 0)


@pytest.mark.parametrize("status", [Status.REJECTED, Status.CANCELLED])
def test_the_money_of_a_request_that_was_refused_or_called_off_can_not_change(status):
    request = make_request()
    ReturnRequest.objects.filter(pk=request.pk).update(status=status)
    request.refresh_from_db()

    services.staff_update(request, return_charge=Decimal("0.00"), refund_amount=Decimal("1.00"))

    request.refresh_from_db()
    assert (request.return_charge, request.refund_amount) == (60, Decimal("440.00"))


def test_the_money_is_fixed_once_the_request_is_completed_but_the_charge_can_still_be_changed_when_the_goods_are_received():
    request = make_request()
    services.change_status(request, Status.APPROVED)
    services.receive_goods(request, [{"item_id": request.items.get().pk, "good": 1, "damaged": 0}])

    services.staff_update(request, return_charge=Decimal("0.00"))  # received: the figures are still being settled
    request.refresh_from_db()
    assert (request.return_charge, request.refund_amount) == (0, 500)

    services.staff_update(request, status=Status.COMPLETED, refund_amount=Decimal("450.00"))  # set together with the completion
    request.refresh_from_db()
    assert request.refund_amount == Decimal("450.00")

    services.staff_update(request, return_charge=Decimal("1.00"), refund_amount=Decimal("1.00"))
    request.refresh_from_db()
    assert (request.return_charge, request.refund_amount) == (0, Decimal("450.00"))  # paid back: fixed


def test_the_shop_cost_is_what_the_customer_does_not_pay_of_the_courier_and_never_negative():
    request = make_request()
    assert request.shop_cost == 0
    ReturnRequest.objects.filter(pk=request.pk).update(return_charge=Decimal("25.00"))
    request.refresh_from_db()
    assert request.shop_cost == Decimal("35.00")
    ReturnRequest.objects.filter(pk=request.pk).update(return_charge=Decimal("90.00"))
    request.refresh_from_db()
    assert request.shop_cost == 0  # charged more than the courier cost: the shop does not pay


# --- the policy -------------------------------------------------------------------------------------------------
def test_without_a_settings_row_the_defaults_apply_and_reading_writes_nothing():
    policy = ReturnSettings.current()
    assert (policy.enabled, policy.window_days, policy.charge_return_delivery) == (True, 7, True)
    assert not ReturnSettings.objects.exists()


def test_the_settings_are_one_row_whatever_is_saved():
    ReturnSettings(window_days=3).save()
    ReturnSettings(window_days=5).save()
    assert list(ReturnSettings.objects.values_list("pk", "window_days")) == [(1, 5)]


def test_the_last_day_is_counted_from_the_day_of_delivery():
    me, _ = signed_in()
    mug, _ = stocked()
    order = delivered_order(me, line(mug), days_ago=2)
    assert services.return_until(order) == timezone.localdate() + timedelta(days=5)  # 7 days from the day it arrived


@pytest.mark.parametrize("reason, free", [("damaged", True), ("wrong_item", True), ("not_as_described", True), ("size_fit", False), ("changed_mind", False), ("other", False)])
def test_which_reasons_are_the_shops_fault(reason, free):
    assert (reason in ReturnRequest.FREE_REASONS) is free
