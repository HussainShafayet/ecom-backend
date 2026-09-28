"""Composes and sends order notifications. Called only from receivers.py, always from inside
transaction.on_commit — never from inside the order's own transaction."""
import logging

from apps.core.utils import mask_email, mask_phone
from apps.orders.models import Order

from .backends import get_notification_backend
from .models import NotificationSettings

logger = logging.getLogger(__name__)

PHONE_AND_EMAIL = ("phone", "email")
EMAIL_ONLY = ("email",)

EVENT_ORDER_PLACED = "order_placed"

# Order.Status -> (event, sentence fragment, channels, NotificationSettings flag). PENDING/PAID/RETURNED are
# absent: no notification, regardless of settings.
STATUS_EVENTS = {
    Order.Status.CONFIRMED: ("order_confirmed", "We're preparing it for shipping.", PHONE_AND_EMAIL, "notify_on_confirmed"),
    Order.Status.SHIPPED: ("order_shipped", "It's on its way to you.", PHONE_AND_EMAIL, "notify_on_shipped"),
    # Delivered is e-mail only: the customer already has the package, so the lower-value channel is skipped.
    Order.Status.DELIVERED: ("order_delivered", "Thanks for shopping with GoCart!", EMAIL_ONLY, "notify_on_delivered"),
    Order.Status.CANCELLED: ("order_cancelled", "If you did not request this, please contact us.", PHONE_AND_EMAIL, "notify_on_cancelled"),
    Order.Status.REFUNDED: ("order_refunded", "The amount will reach you shortly.", PHONE_AND_EMAIL, "notify_on_refunded"),
}


def _mask(target):
    return mask_email(target) if "@" in target else mask_phone(target)


def _send(order, event, message, channels):
    """One attempt per allowed channel (phone only if listed, e-mail only if listed AND given). One
    channel's failure never blocks the other, and neither is ever allowed to raise."""
    targets = []
    if "phone" in channels:
        targets.append(order.phone_number)
    if "email" in channels and order.email:
        targets.append(order.email)
    backend = get_notification_backend()
    for target in targets:
        try:
            backend.send(target=target, message=message, event=event)
        except Exception as exc:  # any provider failure: log it, move on — never raise
            logger.error("Notification delivery failed (event=%s, target=%s)", event, _mask(target), exc_info=exc)


def notify_order_placed(order_pk):
    """Re-fetches the order: the order_placed receiver fires before order.number is assigned, so the
    in-memory instance from the signal must never be used here (see orders/signals.py)."""
    if not NotificationSettings.current().notify_on_placed:
        return
    order = Order.objects.filter(pk=order_pk).first()
    if order is None:  # should not happen; must never raise regardless
        return
    message = (
        f"Hi {order.name}, thank you for your order! Your GoCart order {order.number} has been placed "
        f"and is now being processed."
    )
    _send(order, EVENT_ORDER_PLACED, message, PHONE_AND_EMAIL)


def notify_order_status_changed(order_pk, new_status):
    entry = STATUS_EVENTS.get(new_status)
    if entry is None:
        return
    event, suffix, channels, flag = entry
    if not getattr(NotificationSettings.current(), flag):
        return
    order = Order.objects.filter(pk=order_pk).first()
    if order is None:
        return
    message = f"Hi {order.name}, your GoCart order {order.number} is now {order.get_status_display().lower()}. {suffix}"
    _send(order, event, message, channels)
