from . import services


def keep_product_rating_current(sender, instance, **kwargs):
    """After a review is saved or deleted (an API call, the admin, a cascade from the customer or the product)."""
    services.refresh_product_rating(instance.product_id)
