from django.apps import AppConfig


class CartConfig(AppConfig):
    name = "apps.cart"
    verbose_name = "Cart"

    def ready(self):
        from apps.accounts.signals import guest_data_received

        from .receivers import merge_guest_cart_receiver

        guest_data_received.connect(merge_guest_cart_receiver, dispatch_uid="cart.merge_guest_cart")
