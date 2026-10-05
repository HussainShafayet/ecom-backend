from django.apps import AppConfig


class ReturnsConfig(AppConfig):
    name = "apps.returns"
    verbose_name = "Returns"

    def ready(self):
        from apps.orders import hooks

        from .block import order_returns

        hooks.register_returns_provider(order_returns)
