import logging

from apps.notifications.backends import (
    ConsoleNotificationBackend,
    LocMemNotificationBackend,
    SentNotification,
    get_notification_backend,
)


def test_console_backend_logs_the_message(caplog):
    with caplog.at_level(logging.INFO, logger="apps.notifications"):
        ConsoleNotificationBackend().send(target="+8801712345678", message="hello", event="order_placed")
    assert "hello" in caplog.text
    assert "+8801712345678" in caplog.text
    assert "order_placed" in caplog.text


def test_locmem_backend_appends_to_the_outbox():
    LocMemNotificationBackend.outbox.clear()
    LocMemNotificationBackend().send(target="rahim@example.com", message="hi", event="order_confirmed")
    assert LocMemNotificationBackend.outbox == [
        SentNotification(target="rahim@example.com", message="hi", event="order_confirmed")
    ]
    LocMemNotificationBackend.outbox.clear()


def test_get_notification_backend_reads_the_setting(settings):
    settings.NOTIFICATION_BACKEND = "apps.notifications.backends.ConsoleNotificationBackend"
    assert isinstance(get_notification_backend(), ConsoleNotificationBackend)
