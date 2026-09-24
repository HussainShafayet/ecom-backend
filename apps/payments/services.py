"""Payments: the only code that creates a payment or changes its status. It is driven by the orders app's signals
(`receivers.py`), inside the same transaction as the order, so an order and its payment can never disagree."""
import logging

from django.utils import timezone

from . import state
from .models import Payment
from .providers import provider_for

logger = logging.getLogger(__name__)


class InvalidPaymentTransition(Exception):
    def __init__(self, old, new):
        self.old, self.new = old, new
        super().__init__(f"A {old} payment can not become {new}.")


def open_payment(order):
    """The payment record for a newly placed order (its method decides how it behaves)."""
    return provider_for(order.payment_method).create_payment(order)


def change_payment_status(payment, new_status):
    """Move `payment` along `state.TRANSITIONS`, stamping the dates. Call it inside a transaction with the row
    locked (see `handle_order_status_changed`)."""
    if not state.can_transition(payment.status, new_status):
        raise InvalidPaymentTransition(payment.status, new_status)
    now = timezone.now()
    if new_status == Payment.Status.PAID:
        payment.paid_at = now
    elif new_status == Payment.Status.REFUNDED:
        payment.refunded_at = now
    payment.status = new_status
    payment.save(update_fields=["status", "paid_at", "refunded_at", "updated_at"])
    return payment


def _live_payment(order):
    """The order's live payment, row-locked; one is created when there is none at all (an order from before this app
    existed, or a payment that was lost), so the order's next status change never silently skips the money."""
    live = Payment.objects.select_for_update().filter(order=order, status__in=state.LIVE).first()
    if live is not None:
        return live
    if Payment.objects.filter(order=order).exists():
        return None  # it ended (cancelled or refunded) and nothing is owed any more
    logger.warning("Order %s had no payment; creating one", order.number)
    return open_payment(order)


def handle_order_status_changed(order, new_status):
    """Follow an order's new status: the payment method's provider says what happens to the live payment."""
    payment = _live_payment(order)
    if payment is None:
        return None
    target = provider_for(payment.method).status_after(payment, new_status)
    if target is None or target == payment.status:
        return payment
    return change_payment_status(payment, target)
