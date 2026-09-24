from django.apps import AppConfig


class WishlistConfig(AppConfig):
    name = "apps.wishlist"
    verbose_name = "Wishlist"

    def ready(self):
        from apps.accounts.signals import guest_data_received
        from apps.catalog.favourites import register_favourite_provider

        from .receivers import merge_guest_favourites_receiver
        from .services import favourite_ids

        register_favourite_provider(favourite_ids)  # what fills `is_favourite` in the catalog
        guest_data_received.connect(merge_guest_favourites_receiver, dispatch_uid="wishlist.merge_guest_favourites")
