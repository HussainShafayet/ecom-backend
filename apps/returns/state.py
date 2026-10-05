"""The return request status flow: the ONE place that says which status may follow which.

    requested -> approved | rejected | cancelled
    approved  -> received | cancelled
    received  -> completed
    rejected, completed, cancelled: final

`approved` is the shop agreeing to take the goods back. `received` is the goods being back and entered (`services.receive_goods`: the good
units go back on the shelf, the damaged ones are counted, and nothing is cancelled any more); `completed` is the money paid back. A customer
may cancel while the request is still `requested`; after an approval only the shop calls it off (the goods never came, the customer changed
their mind and phoned), through the admin. Once the goods are received the stock has moved, so there is no way back.
"""
from .models import ReturnRequest

Status = ReturnRequest.Status

TRANSITIONS = {
    Status.REQUESTED: (Status.APPROVED, Status.REJECTED, Status.CANCELLED),
    Status.APPROVED: (Status.RECEIVED, Status.CANCELLED),
    Status.RECEIVED: (Status.COMPLETED,),
    Status.REJECTED: (),
    Status.COMPLETED: (),
    Status.CANCELLED: (),
}

# These hold units of their order's lines: a customer can not ask for the same unit twice. A rejected or cancelled request
# lets go of its units, so the customer may ask again.
HOLDING = (Status.REQUESTED, Status.APPROVED, Status.RECEIVED, Status.COMPLETED)

# Nothing left to decide about the money of these
MONEY_LOCKED = (Status.REJECTED, Status.COMPLETED, Status.CANCELLED)


def allowed_next(status):
    """The statuses a request in `status` may move to (an unknown status has none)."""
    return TRANSITIONS.get(status, ())


def can_transition(old, new):
    return new in allowed_next(old)
