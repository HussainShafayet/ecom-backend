import pytest

from apps.orders.models import Order
from apps.payments import state
from apps.payments.models import Payment
from apps.payments.providers import PROVIDERS, CashOnDelivery, provider_for
from apps.payments.services import InvalidPaymentTransition, change_payment_status
from apps.payments.tests.helpers import payment_of, placed

pytestmark = pytest.mark.django_db

PS = Payment.Status
OS = Order.Status
ALLOWED = {
    (PS.PENDING, PS.PAID),
    (PS.PENDING, PS.CANCELLED),
    (PS.PAID, PS.REFUNDED),
}


@pytest.mark.parametrize("old", list(PS))
@pytest.mark.parametrize("new", list(PS))
def test_the_payment_transition_map(old, new):
    assert state.can_transition(old, new) is ((old, new) in ALLOWED)


def test_a_forbidden_transition_raises_and_changes_nothing():
    order, _ = placed()
    payment = payment_of(order)
    with pytest.raises(InvalidPaymentTransition, match="pending payment can not become refunded"):
        change_payment_status(payment, PS.REFUNDED)
    payment.refresh_from_db()
    assert payment.status == "pending"


def test_the_dates_are_stamped_by_the_service():
    order, _ = placed()
    payment = payment_of(order)
    change_payment_status(payment, PS.PAID)
    assert payment.paid_at is not None and payment.refunded_at is None
    change_payment_status(payment, PS.REFUNDED)
    assert payment.refunded_at is not None


# What cash on delivery does for every (order status, payment status): the table of `CashOnDelivery.EFFECTS`.
EXPECTED = {
    (OS.PAID, PS.PENDING): PS.PAID,
    (OS.DELIVERED, PS.PENDING): PS.PAID,
    (OS.CANCELLED, PS.PENDING): PS.CANCELLED,
    (OS.CANCELLED, PS.PAID): PS.REFUNDED,
    (OS.RETURNED, PS.PENDING): PS.CANCELLED,  # a parcel that came back was never paid for at the door
    (OS.RETURNED, PS.PAID): PS.REFUNDED,  # cash collected earlier is given back
    (OS.REFUNDED, PS.PENDING): PS.CANCELLED,
    (OS.REFUNDED, PS.PAID): PS.REFUNDED,
}


@pytest.mark.parametrize("payment_status", list(PS))
@pytest.mark.parametrize("order_status", list(OS))
def test_cash_on_delivery_effects(order_status, payment_status):
    payment = Payment(method="cod", status=payment_status)
    assert CashOnDelivery().status_after(payment, order_status) == EXPECTED.get((order_status, payment_status))


def test_every_effect_is_an_allowed_transition():
    for (order_status, payment_status), target in EXPECTED.items():
        assert state.can_transition(payment_status, target), (order_status, payment_status, target)


def test_the_registry_knows_cash_on_delivery_only():
    assert set(PROVIDERS) == {"cod"}
    assert isinstance(provider_for("cod"), CashOnDelivery)
    with pytest.raises(LookupError, match="no payment provider for 'bkash'"):
        provider_for("bkash")


def test_the_base_provider_makes_subclasses_say_what_they_do():
    from apps.payments.providers import PaymentProvider

    with pytest.raises(NotImplementedError):
        PaymentProvider().create_payment(None)
    with pytest.raises(NotImplementedError):
        PaymentProvider().status_after(None, "paid")
