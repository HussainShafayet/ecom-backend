"""The order status flow: the ONE place that says which status may follow which.

    pending   -> confirmed | paid | shipped | cancelled
    confirmed -> paid | shipped | cancelled
    paid      -> shipped | cancelled | refunded
    shipped   -> delivered | returned | cancelled
    delivered -> refunded
    cancelled, returned, refunded: final

`confirmed` and `paid` are optional steps: a cash-on-delivery order normally goes pending -> shipped -> delivered
(the cash is collected at the door, the payment turns paid then), a shop that phones its customers adds `confirmed`,
a prepaid order goes through `paid`. `returned` is a shipped parcel that came back (delivery failed, or the customer
refused it).

`services.change_status` is the only code that changes a status, and it asks this module first.

Stock goes back on the shelf (`RESTOCKING`) when the goods did not reach the customer: an order cancelled while it
was pending, confirmed, paid or shipped (a shipped parcel that is cancelled is assumed to come back), a shipped
parcel that came back (`returned`), and a paid order that is refunded before it was shipped. It does NOT when a
*delivered* order is refunded: the goods already left, whether they are returned in a sellable state is a decision
for a person, who can edit the stock in the admin. (Returned goods are put back on the shelf like a cancelled parcel;
if they are damaged, a person corrects the stock.)
"""
from .models import Order

Status = Order.Status

TRANSITIONS = {
    Status.PENDING: (Status.CONFIRMED, Status.PAID, Status.SHIPPED, Status.CANCELLED),
    Status.CONFIRMED: (Status.PAID, Status.SHIPPED, Status.CANCELLED),
    Status.PAID: (Status.SHIPPED, Status.CANCELLED, Status.REFUNDED),
    Status.SHIPPED: (Status.DELIVERED, Status.RETURNED, Status.CANCELLED),
    Status.DELIVERED: (Status.REFUNDED,),
    Status.CANCELLED: (),
    Status.RETURNED: (),
    Status.REFUNDED: (),
}

RESTOCKING = frozenset(
    {
        (Status.PENDING, Status.CANCELLED),
        (Status.CONFIRMED, Status.CANCELLED),
        (Status.PAID, Status.CANCELLED),
        (Status.SHIPPED, Status.CANCELLED),
        (Status.SHIPPED, Status.RETURNED),
        (Status.PAID, Status.REFUNDED),
    }
)


def allowed_next(status):
    """The statuses an order in `status` may move to (an unknown status has none)."""
    return TRANSITIONS.get(status, ())


def can_transition(old, new):
    return new in allowed_next(old)


def restocks(old, new):
    """True when moving from `old` to `new` puts the ordered quantities back into stock."""
    return (old, new) in RESTOCKING
