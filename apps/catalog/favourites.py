"""The hook behind `is_favourite`.

The catalog never imports the wishlist (the wishlist depends on the catalog, not the other way round). The
wishlist app registers a provider from its `AppConfig.ready()`; until it exists nobody has favourites.
"""

_providers = []


def register_favourite_provider(provider):
    """`provider(user, product_ids)` returns the ids among `product_ids` that `user` has favourited."""
    if provider not in _providers:
        _providers.append(provider)


def favourite_product_ids(user, product_ids):
    """The favourited ids among `product_ids` for `user` (empty for guests). One provider call per page."""
    if not product_ids or not getattr(user, "is_authenticated", False):
        return frozenset()
    found = set()
    for provider in _providers:
        found.update(provider(user, list(product_ids)))
    return frozenset(found)
