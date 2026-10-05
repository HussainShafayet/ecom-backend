"""The `returns` block of an order's detail (`GET /orders/{order_id}/`): can the customer ask to return something, what it would cost them,
and what they asked so far. Registered with `orders.hooks` from `apps.py`, so `orders` never imports this app."""
from apps.orders.models import Order

from . import services
from .models import ReturnRequest, ReturnSettings
from .serializers import ReturnRequestSerializer


def order_returns(order):
    policy = ReturnSettings.current()
    requests = order.return_requests.prefetch_related("items__order_item")
    delivered = order.status == Order.Status.DELIVERED

    message = services.refusal(order, policy) if delivered else None
    free = services.returnable_units(order) if delivered and message is None else {}
    if delivered and message is None and not free:
        message = services.NOTHING_LEFT
    return {
        "can_request": bool(free),
        "message": message,
        "until": services.return_until(order, policy) if delivered and policy.enabled else None,
        # what a reason that is not free costs the customer (taken off the refund); each reason says whether it is free
        "return_charge": order.delivery_charge if policy.charge_return_delivery else 0,
        "reasons": [
            {
                "value": value,
                "label": label,
                "free": not policy.charge_return_delivery or value in ReturnRequest.FREE_REASONS,
            }
            for value, label in ReturnRequest.Reason.choices
        ],
        "items": [{"item_id": pk, "quantity": units} for pk, units in free.items()],
        "requests": ReturnRequestSerializer(requests, many=True).data,
    }
