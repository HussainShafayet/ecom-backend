"""The payment status flow, the ONE place that says which status may follow which.

    pending -> paid | cancelled
    paid    -> refunded
    cancelled, refunded: final

`services.change_payment_status` is the only code that changes a payment's status, and it asks this module first.
"""
from .models import Payment

Status = Payment.Status

TRANSITIONS = {
    Status.PENDING: (Status.PAID, Status.CANCELLED),
    Status.PAID: (Status.REFUNDED,),
    Status.CANCELLED: (),
    Status.REFUNDED: (),
}

LIVE = (Status.PENDING, Status.PAID)  # a payment that still counts (at most one per order)


def can_transition(old, new):
    return new in TRANSITIONS.get(old, ())
