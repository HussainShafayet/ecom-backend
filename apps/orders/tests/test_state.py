"""The transition map, written out here in full and independently of `state.py`, so a change to it fails a test."""
import itertools

import pytest

from apps.orders import state
from apps.orders.models import Order

Status = Order.Status
ALL = [
    Status.PENDING,
    Status.CONFIRMED,
    Status.PAID,
    Status.SHIPPED,
    Status.DELIVERED,
    Status.RETURNED,
    Status.CANCELLED,
    Status.REFUNDED,
]

ALLOWED = {
    ("pending", "confirmed"),
    ("pending", "paid"),
    ("pending", "shipped"),
    ("pending", "cancelled"),
    ("confirmed", "paid"),
    ("confirmed", "shipped"),
    ("confirmed", "cancelled"),
    ("paid", "shipped"),
    ("paid", "cancelled"),
    ("paid", "refunded"),
    ("shipped", "delivered"),
    ("shipped", "returned"),
    ("shipped", "cancelled"),
    ("delivered", "refunded"),
}
RESTOCKING = {
    ("pending", "cancelled"),
    ("confirmed", "cancelled"),
    ("paid", "cancelled"),
    ("shipped", "cancelled"),
    ("shipped", "returned"),
    ("paid", "refunded"),
}
ORIGINAL_SIX = ["pending", "paid", "shipped", "delivered", "cancelled", "refunded"]  # what the frontend was built on


def test_the_statuses_are_the_original_six_plus_confirmed_and_returned():
    assert set(ORIGINAL_SIX) <= set(Status.values)  # nothing the frontend knew was renamed or removed
    assert [status.value for status in ALL] == [
        "pending", "confirmed", "paid", "shipped", "delivered", "returned", "cancelled", "refunded"
    ]
    assert list(Status.values) == [status.value for status in ALL]
    assert {"confirmed", "returned"} == set(Status.values) - set(ORIGINAL_SIX)


@pytest.mark.parametrize("old, new", list(itertools.product(ALL, ALL)))
def test_every_pair_of_statuses(old, new):
    assert state.can_transition(old, new) is ((old.value, new.value) in ALLOWED)


@pytest.mark.parametrize("old, new", list(itertools.product(ALL, ALL)))
def test_which_transitions_put_the_goods_back(old, new):
    assert state.restocks(old, new) is ((old.value, new.value) in RESTOCKING)


@pytest.mark.parametrize("status", [Status.CANCELLED, Status.RETURNED, Status.REFUNDED])
def test_cancelled_returned_and_refunded_are_final(status):
    assert state.allowed_next(status) == ()


def test_every_restocking_transition_is_an_allowed_one():
    assert state.RESTOCKING <= {(old, new) for old in ALL for new in state.allowed_next(old)}


def test_a_delivered_order_that_is_refunded_is_not_restocked():
    assert not state.restocks(Status.DELIVERED, Status.REFUNDED)


def test_confirming_and_paying_are_optional_steps():
    """A cash-on-delivery order may go straight from pending to shipped: neither step is required."""
    assert state.can_transition(Status.PENDING, Status.SHIPPED)
    assert state.can_transition(Status.PENDING, Status.CONFIRMED) and state.can_transition(Status.CONFIRMED, Status.SHIPPED)
    assert state.can_transition(Status.PENDING, Status.PAID) and state.can_transition(Status.PAID, Status.SHIPPED)


def test_only_a_shipped_parcel_can_come_back_and_it_goes_back_on_the_shelf():
    assert [old.value for old in ALL if state.can_transition(old, Status.RETURNED)] == ["shipped"]
    assert state.restocks(Status.SHIPPED, Status.RETURNED)


def test_nothing_skips_the_shipping():
    """Delivered and returned are only ever reached from shipped."""
    for target in (Status.DELIVERED, Status.RETURNED):
        assert [old.value for old in ALL if state.can_transition(old, target)] == ["shipped"]


def test_plain_strings_work_like_the_enum():
    assert state.can_transition("pending", "shipped")
    assert not state.can_transition("delivered", "pending")
    assert state.allowed_next("shipped") == (Status.DELIVERED, Status.RETURNED, Status.CANCELLED)
    assert state.restocks("paid", "refunded")


def test_an_unknown_status_goes_nowhere():
    assert state.allowed_next("lost") == ()
    assert not state.can_transition("lost", "pending") and not state.can_transition("pending", "lost")
