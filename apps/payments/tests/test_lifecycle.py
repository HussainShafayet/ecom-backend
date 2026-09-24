from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.orders.tests.helpers import line, place, set_charges, signed_in, stocked
from apps.payments import services
from apps.payments.models import Payment
from apps.payments.tests.helpers import Status, move, payment_of, placed

pytestmark = pytest.mark.django_db


# --- opening -------------------------------------------------------------------------------------------
def test_placing_an_order_opens_one_pending_cash_payment_for_the_whole_total():
    order, _ = placed(quantity=2, price="500.00")  # 1000.00 + 60.00 delivery

    payment = payment_of(order)

    assert (payment.method, payment.status) == ("cod", "pending")
    assert payment.amount == order.total == Decimal("1060.00")
    assert payment.paid_at is None and payment.refunded_at is None


def test_guests_and_signed_in_customers_both_get_one(api_client):
    mug, _ = stocked("Mug", stock=10)
    _, member = signed_in()
    assert place(api_client, line(mug)).status_code == 201
    assert place(member, line(mug)).status_code == 201
    assert Payment.objects.count() == 2
    assert set(Payment.objects.values_list("status", flat=True)) == {"pending"}


def test_an_order_that_is_refused_leaves_no_payment(api_client):
    mug, _ = stocked("Mug", stock=1)
    assert place(api_client, line(mug, quantity=5)).status_code == 400
    assert Payment.objects.count() == 0


def test_the_amount_is_a_snapshot_of_the_total():
    order, _ = placed(quantity=1, price="500.00")
    set_charges(inside="99.00")  # the shop changes its delivery charge afterwards
    assert payment_of(order).amount == Decimal("560.00")


# --- following the order -----------------------------------------------------------------------------------
P, S, D, C, R = Status.PAID, Status.SHIPPED, Status.DELIVERED, Status.CANCELLED, Status.REFUNDED

WALKS = [
    ((), "pending"),
    ((S,), "pending"),  # on its way: nothing collected yet
    ((S, D), "paid"),  # the courier collects the cash
    ((S, D, R), "refunded"),
    ((C,), "cancelled"),
    ((S, C), "cancelled"),  # a parcel that comes back was never paid
    ((P,), "paid"),  # staff marked it paid
    ((P, S), "paid"),
    ((P, S, D), "paid"),  # delivering an already paid order does not collect twice
    ((P, R), "refunded"),
    ((P, C), "refunded"),  # cash that was collected goes back
    ((P, S, C), "refunded"),
    ((P, S, D, R), "refunded"),
]


@pytest.mark.parametrize(("walk", "expected"), WALKS, ids=["-".join(w) or "placed" for w, _ in WALKS])
def test_the_payment_follows_the_order(walk, expected):
    order, _ = placed()
    move(order, *walk)
    assert Payment.objects.filter(order=order).count() == 1  # never a second one
    assert payment_of(order).status == expected


def test_paid_at_is_stamped_once_when_the_cash_arrives():
    order, _ = placed()
    move(order, S)
    assert payment_of(order).paid_at is None
    move(order, D)
    paid_at = payment_of(order).paid_at
    assert paid_at is not None
    move(order, R)
    payment = payment_of(order)
    assert payment.paid_at == paid_at  # the refund keeps when it was collected
    assert payment.refunded_at is not None and payment.refunded_at >= paid_at


def test_delivering_an_order_staff_already_marked_paid_keeps_the_first_paid_at():
    order, _ = placed()
    move(order, P)
    first = payment_of(order).paid_at
    move(order, S, D)
    assert payment_of(order).paid_at == first


def test_a_cancelled_payment_was_never_collected():
    order, _ = placed()
    move(order, C)
    payment = payment_of(order)
    assert payment.status == "cancelled"
    assert payment.paid_at is None and payment.refunded_at is None


# --- healing ---------------------------------------------------------------------------------------------
def test_an_order_without_a_payment_gets_one_at_its_next_status_change():
    order, _ = placed()
    Payment.objects.all().delete()  # from before payments existed, or lost
    move(order, S, D)
    assert Payment.objects.filter(order=order).count() == 1
    assert payment_of(order).status == "paid"


def test_an_ended_payment_is_not_recreated():
    order, _ = placed()
    move(order, C)
    assert services.handle_order_status_changed(order, Status.REFUNDED) is None
    assert Payment.objects.filter(order=order).count() == 1
    assert payment_of(order).status == "cancelled"


# --- the database backstops --------------------------------------------------------------------------------
def test_an_order_has_at_most_one_live_payment():
    order, _ = placed()
    with pytest.raises(IntegrityError), transaction.atomic():
        Payment.objects.create(order=order, method="cod", status="pending", amount=order.total)


def test_a_new_payment_is_fine_once_the_old_one_ended():
    order, _ = placed()
    move(order, C)
    Payment.objects.create(order=order, method="cod", status="pending", amount=order.total)
    assert Payment.objects.filter(order=order).count() == 2


@pytest.mark.parametrize("status", ["paid", "refunded"])
def test_a_collected_payment_must_say_when(status):
    order, _ = placed()
    with pytest.raises(IntegrityError), transaction.atomic():
        Payment.objects.filter(order=order).update(status=status, paid_at=None, refunded_at=None)


def test_a_refunded_payment_must_say_when_it_was_refunded():
    order, _ = placed()
    move(order, S, D)
    with pytest.raises(IntegrityError), transaction.atomic():
        Payment.objects.filter(order=order).update(status="refunded", refunded_at=None)


def test_an_order_with_a_payment_can_not_be_deleted():
    order, _ = placed()
    from django.db.models import ProtectedError

    with pytest.raises(ProtectedError):
        order.delete()
