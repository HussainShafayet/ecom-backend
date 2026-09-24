def merge_guest_cart_receiver(sender, user, cart=None, **kwargs):
    """`accounts.signals.guest_data_received`: fold the guest's browser cart into the customer's cart."""
    from .services import merge_guest_cart

    merge_guest_cart(user, cart or [])
