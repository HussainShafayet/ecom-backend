"""The hook behind the `payment` block of an order.

`orders` never imports `payments` (the payments app listens to the order signals and depends on orders, not the other
way round). The payments app registers a provider from its `AppConfig.ready()`; until it exists an order shows no
payment.
"""

_providers = []


def register_payment_info_provider(provider):
    """`provider(orders)` returns `{order.pk: {"method", "status", "amount", "paid_at", ...}}` for those orders that
    have a payment. One call per page of orders, so a provider must not query once per order."""
    if provider not in _providers:
        _providers.append(provider)


def payment_info(orders):
    """`{order.pk: dict}` for the orders that have a payment (an order without one is missing from the result)."""
    found = {}
    orders = list(orders)
    if orders:
        for provider in _providers:
            found.update(provider(orders))
    return found
