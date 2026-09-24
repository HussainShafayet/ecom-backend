"""The transition map, written out here in full and independently of `state.py`, so a change to it fails a test."""
import itertools

import pytest

from apps.orders import state
from apps.orders.models import Order

Status = Order.Status
ALL = [Status.PENDING, Status.PAID, Status.SHIPPED, Status.DELIVERED, Status.CANCELLED, Status.REFUNDED]

ALLOWED = {
    ("pending", "paid"),
    ("pending", "shipped"),
    ("pending", "cancelled"),
    ("paid", "shipped"),
    ("paid", "cancelled"),
    ("paid", "refunded"),
    ("shipped", "delivered"),
    ("shipped", "cancelled"),
    ("delivered", "refunded"),
}
RESTOCKING = {("pending", "cancelled"), ("paid", "cancelled"), ("shipped", "cancelled"), ("paid", "refunded")}


def test_the_six_statuses_are_the_contract_ones():
    assert [status.value for status in ALL] == ["pending", "paid", "shipped", "delivered", "cancelled", "refunded"]
    assert set(Status.values) == {status.value for status in ALL}


@pytest.mark.parametrize("old, new", list(itertools.product(ALL, ALL)))
def test_every_pair_of_statuses(old, new):
    assert state.can_transition(old, new) is ((old.value, new.value) in ALLOWED)


@pytest.mark.parametrize("old, new", list(itertools.product(ALL, ALL)))
def test_which_transitions_put_the_goods_back(old, new):
    assert state.restocks(old, new) is ((old.value, new.value) in RESTOCKING)


@pytest.mark.parametrize("status", [Status.CANCELLED, Status.REFUNDED])
def test_cancelled_and_refunded_are_final(status):
    assert state.allowed_next(status) == ()


def test_every_restocking_transition_is_an_allowed_one():
    assert state.RESTOCKING <= {(old, new) for old in ALL for new in state.allowed_next(old)}


def test_a_delivered_order_that_is_refunded_is_not_restocked():
    assert not state.restocks(Status.DELIVERED, Status.REFUNDED)


def test_plain_strings_work_like_the_enum():
    assert state.can_transition("pending", "shipped")
    assert not state.can_transition("delivered", "pending")
    assert state.allowed_next("shipped") == (Status.DELIVERED, Status.CANCELLED)
    assert state.restocks("paid", "refunded")


def test_an_unknown_status_goes_nowhere():
    assert state.allowed_next("lost") == ()
    assert not state.can_transition("lost", "pending") and not state.can_transition("pending", "lost")
