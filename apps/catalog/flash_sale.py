"""The flash sale's window, as the storefront needs it.

The window is optional. With none set (no row, or both ends empty) every product and category marked `is_flash_sale` shows,
always, and there is nothing to count down to: how the shop worked before this existed. With one set, the marked products show
only while it is live, and the sale endpoints say how long is left so the storefront can count down without trusting the
customer's own clock (a phone's clock may be wrong, the seconds are measured here)."""
import math

from django.utils import timezone

from .models import FlashSale


def _seconds_until(moment, now):
    return max(0, math.ceil((moment - now).total_seconds()))


def flash_sale_state(now=None):
    """`None` when no window is set, else
    `{starts_at, ends_at, is_live, starts_in_seconds, ends_in_seconds}`: the seconds are `None` where they do not apply (no start
    or already started; no end), and `ends_in_seconds` is 0 once it is over."""
    sale = FlashSale.current()
    if sale.starts_at is None and sale.ends_at is None:
        return None
    now = now or timezone.now()
    started = sale.starts_at is None or now >= sale.starts_at
    ended = sale.ends_at is not None and now >= sale.ends_at
    return {
        "starts_at": sale.starts_at,
        "ends_at": sale.ends_at,
        "is_live": started and not ended,
        "starts_in_seconds": None if started else _seconds_until(sale.starts_at, now),
        "ends_in_seconds": None if sale.ends_at is None else (0 if ended else _seconds_until(sale.ends_at, now)),
    }


def is_live(state):
    """Whether the marked products show right now: no window means always."""
    return state is None or state["is_live"]
