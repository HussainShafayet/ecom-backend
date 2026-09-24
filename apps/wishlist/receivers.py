def merge_guest_favourites_receiver(sender, user, favorites=None, **kwargs):
    """`accounts.signals.guest_data_received`: the frontend spells the key `favorite`."""
    from .services import merge_guest_favourites

    merge_guest_favourites(user, favorites or [])
