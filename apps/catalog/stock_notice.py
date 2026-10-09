"""The "Only N left" notice: how few units the shop lets customers see.

The product API never gives the stock away. Only when a product (or one size of it) has 1 to `StockNotice.show_when_left` units does it answer
`stock_left` with the real number, so the storefront can say "Only 3 left"; with more, or none, it answers null. The setting is read once per
serializer (so once per response), never per product."""
from .models import StockNotice


def threshold():
    """How many units or fewer are shown (0: never). Reading never writes."""
    return StockNotice.current().show_when_left


def left_if_low(stock, notice_at):
    """`stock` when it is 1 to `notice_at`, else None (plenty, sold out, unknown, or the notice is off)."""
    if not notice_at or stock is None:
        return None
    return stock if 0 < stock <= notice_at else None
