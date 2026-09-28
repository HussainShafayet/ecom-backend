"""How the customer learns their order was placed/confirmed/shipped/delivered/cancelled/refunded. Pick one with
the NOTIFICATION_BACKEND setting (dotted path) — same idea as OTP_BACKEND.

To add a real SMS/e-mail provider: subclass NotificationBackend, implement `send`, and point
NOTIFICATION_BACKEND at it. `target` is a phone number or an e-mail address; `event` is one of "order_placed",
"order_confirmed", "order_shipped", "order_delivered", "order_cancelled", "order_refunded" (see services.py).

Unlike OTP delivery, a notification failure must never break the order flow: services.py always catches and logs
whatever `send` raises. This layer itself never needs to worry about that.
"""
import logging
from dataclasses import dataclass
from typing import ClassVar

from django.conf import settings
from django.utils.module_loading import import_string

logger = logging.getLogger("apps.notifications")


class NotificationBackend:
    def send(self, *, target, message, event):
        raise NotImplementedError


class ConsoleNotificationBackend(NotificationBackend):
    """DEV ONLY (and the default everywhere, until a real provider is chosen): prints the message to the
    server log instead of sending a real SMS/e-mail."""

    def send(self, *, target, message, event):
        logger.info("[DEV ONLY] Notification for %s (%s): %s", target, event, message)


@dataclass(frozen=True)
class SentNotification:
    target: str
    message: str
    event: str


class LocMemNotificationBackend(NotificationBackend):
    """Keeps sent notifications in `outbox` (like Django's locmem e-mail backend); used by the tests."""

    outbox: ClassVar[list] = []

    def send(self, *, target, message, event):
        self.outbox.append(SentNotification(target=target, message=message, event=event))


def get_notification_backend():
    return import_string(settings.NOTIFICATION_BACKEND)()
