"""Shared by the returns tests."""
from datetime import timedelta

from django.utils import timezone

from apps.orders import services as order_services
from apps.orders.models import Order, OrderStatusHistory
from apps.orders.tests.helpers import ORDERS, make_order  # noqa: F401  (re-exported for the tests)


def delivered_order(user, *items, days_ago=0, **overrides):
    """An order of `user` that the shop delivered `days_ago` days ago (the history row is what the return window counts from)."""
    order = make_order(*items, user=user, **overrides)
    order_services.change_status(order, Order.Status.SHIPPED)
    order_services.change_status(order, Order.Status.DELIVERED)
    if days_ago:
        OrderStatusHistory.objects.filter(order=order, to_status=Order.Status.DELIVERED).update(
            created_at=timezone.now() - timedelta(days=days_ago)
        )
    return order


def returns_url(order):
    return f"{ORDERS}{order.number}/returns/"


def cancel_url(order, request_id):
    return f"{ORDERS}{order.number}/returns/{request_id}/cancel/"


def body(order, *entries, reason="damaged", **extra):
    """The body the shop's form posts: `entries` are `(line index, units)` pairs, the line index counting the order's lines from 0."""
    items = list(order.items.all())
    return {"reason": reason, "items": [{"item_id": items[index].pk, "quantity": units} for index, units in entries], **extra}


def approved_and_received(request, good=None, damaged=0):
    """Approve `request` and receive its goods: by default every unit came back fine."""
    from apps.returns import services
    from apps.returns.models import ReturnRequest

    services.change_status(request, ReturnRequest.Status.APPROVED)
    lines = [{"item_id": item.pk, "good": item.quantity if good is None else good, "damaged": damaged} for item in request.items.all()]
    return services.receive_goods(request, lines)
