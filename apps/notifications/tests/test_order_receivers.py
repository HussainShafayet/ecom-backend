import pytest

from apps.cart.tests.helpers import stocked
from apps.notifications.models import NotificationSettings
from apps.orders import services as order_services
from apps.orders.models import Order
from apps.orders.tests.helpers import line, make_order

pytestmark = pytest.mark.django_db


def _place(django_capture_on_commit_callbacks, **overrides):
    mug, _ = stocked("Mug", stock=10)
    with django_capture_on_commit_callbacks(execute=True):
        order = make_order(line(mug), **overrides)
    return order


def test_placing_an_order_notifies_phone_and_email(django_capture_on_commit_callbacks, notification_outbox):
    order = _place(django_capture_on_commit_callbacks, email="rahim@example.com")
    assert len(notification_outbox) == 2
    sms, mail = notification_outbox
    assert sms.target == order.phone_number and sms.event == "order_placed"
    assert order.number in sms.message and order.name in sms.message
    assert mail.target == order.email and mail.event == "order_placed"
    assert mail.message == sms.message


def test_placing_an_order_without_an_email_only_notifies_the_phone(django_capture_on_commit_callbacks, notification_outbox):
    order = _place(django_capture_on_commit_callbacks, email="")
    assert len(notification_outbox) == 1
    assert notification_outbox[0].target == order.phone_number


def test_confirmed_and_shipped_each_notify_both_channels(django_capture_on_commit_callbacks, notification_outbox):
    order = _place(django_capture_on_commit_callbacks, email="rahim@example.com")
    notification_outbox.clear()

    with django_capture_on_commit_callbacks(execute=True):
        order_services.change_status(order, Order.Status.CONFIRMED)
    assert [n.event for n in notification_outbox] == ["order_confirmed", "order_confirmed"]
    assert "confirmed" in notification_outbox[0].message.lower()
    notification_outbox.clear()

    with django_capture_on_commit_callbacks(execute=True):
        order_services.change_status(order, Order.Status.SHIPPED)
    assert [n.event for n in notification_outbox] == ["order_shipped", "order_shipped"]
    assert "shipped" in notification_outbox[0].message.lower()


def test_delivered_only_notifies_email_when_given(django_capture_on_commit_callbacks, notification_outbox):
    order = _place(django_capture_on_commit_callbacks, email="rahim@example.com")
    order_services.change_status(order, Order.Status.CONFIRMED)
    order_services.change_status(order, Order.Status.SHIPPED)
    notification_outbox.clear()

    with django_capture_on_commit_callbacks(execute=True):
        order_services.change_status(order, Order.Status.DELIVERED)
    assert len(notification_outbox) == 1
    assert notification_outbox[0].target == order.email
    assert notification_outbox[0].event == "order_delivered"


def test_delivered_notifies_nothing_without_an_email(django_capture_on_commit_callbacks, notification_outbox):
    order = _place(django_capture_on_commit_callbacks, email="")
    order_services.change_status(order, Order.Status.CONFIRMED)
    order_services.change_status(order, Order.Status.SHIPPED)
    notification_outbox.clear()

    with django_capture_on_commit_callbacks(execute=True):
        order_services.change_status(order, Order.Status.DELIVERED)
    assert notification_outbox == []


def test_cancelled_and_refunded_notify_both_channels(django_capture_on_commit_callbacks, notification_outbox):
    order = _place(django_capture_on_commit_callbacks, email="rahim@example.com")
    notification_outbox.clear()

    with django_capture_on_commit_callbacks(execute=True):
        order_services.change_status(order, Order.Status.CANCELLED)
    assert [n.event for n in notification_outbox] == ["order_cancelled", "order_cancelled"]

    order2 = _place(django_capture_on_commit_callbacks, email="rahim@example.com")
    order_services.change_status(order2, Order.Status.PAID)
    notification_outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        order_services.change_status(order2, Order.Status.REFUNDED)
    assert [n.event for n in notification_outbox] == ["order_refunded", "order_refunded"]


def test_paid_sends_nothing(django_capture_on_commit_callbacks, notification_outbox):
    order = _place(django_capture_on_commit_callbacks, email="rahim@example.com")
    notification_outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        order_services.change_status(order, Order.Status.PAID)
    assert notification_outbox == []


def test_the_receivers_are_connected_once(django_capture_on_commit_callbacks, notification_outbox):
    """Mirrors payments' test_the_receivers_are_connected_once: two connections would double every message."""
    order = _place(django_capture_on_commit_callbacks, email="rahim@example.com")
    assert len(notification_outbox) == 2  # not 4
    notification_outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        order_services.change_status(order, Order.Status.CONFIRMED)
    assert len(notification_outbox) == 2  # not 4


def test_switching_an_event_off_silences_only_that_event(django_capture_on_commit_callbacks, notification_outbox):
    settings_row = NotificationSettings.load()
    settings_row.notify_on_confirmed = False
    settings_row.save()

    order = _place(django_capture_on_commit_callbacks, email="rahim@example.com")
    notification_outbox.clear()

    with django_capture_on_commit_callbacks(execute=True):
        order_services.change_status(order, Order.Status.CONFIRMED)
    assert notification_outbox == []

    with django_capture_on_commit_callbacks(execute=True):
        order_services.change_status(order, Order.Status.SHIPPED)
    assert [n.event for n in notification_outbox] == ["order_shipped", "order_shipped"]


def test_switching_placed_off_silences_the_placed_notification(django_capture_on_commit_callbacks, notification_outbox):
    settings_row = NotificationSettings.load()
    settings_row.notify_on_placed = False
    settings_row.save()

    _place(django_capture_on_commit_callbacks, email="rahim@example.com")
    assert notification_outbox == []


def test_the_default_settings_have_every_event_on():
    settings_row = NotificationSettings()  # unsaved: current()'s fallback when no row exists yet
    assert settings_row.notify_on_placed
    assert settings_row.notify_on_confirmed
    assert settings_row.notify_on_shipped
    assert settings_row.notify_on_delivered
    assert settings_row.notify_on_cancelled
    assert settings_row.notify_on_refunded
