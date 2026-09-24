from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    name = "apps.payments"
    verbose_name = "Payments"

    def ready(self):
        from apps.orders.signals import order_placed, order_status_changed

        from .receivers import on_order_placed, on_order_status_changed

        order_placed.connect(on_order_placed, dispatch_uid="payments.on_order_placed")
        order_status_changed.connect(on_order_status_changed, dispatch_uid="payments.on_order_status_changed")
