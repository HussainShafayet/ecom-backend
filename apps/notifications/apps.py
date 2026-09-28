from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    name = "apps.notifications"
    verbose_name = "Notifications"

    def ready(self):
        from apps.orders.signals import order_placed, order_status_changed

        from .receivers import on_order_placed, on_order_status_changed

        order_placed.connect(on_order_placed, dispatch_uid="notifications.on_order_placed")
        order_status_changed.connect(on_order_status_changed, dispatch_uid="notifications.on_order_status_changed")
