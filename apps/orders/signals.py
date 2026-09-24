"""What the orders app announces, so other apps (payments) can react without `orders` importing them.

Both are sent INSIDE the transaction of `place_order` / `change_status` with `send()` (not `send_robust`): a receiver
that fails rolls the whole order or status change back, so an order never exists without what depends on it.
"""
from django.dispatch import Signal

# order: the new `Order` with its lines and its stock movement written. Its `number` is NOT assigned yet (that
# happens last, to keep the per-day counter lock short), so receivers must not use it; do anything that needs
# the number (an e-mail, an SMS) in `transaction.on_commit`.
order_placed = Signal()

# order: the locked `Order` (its status is already the new one), old / new: status values, by: the staff user or None.
order_status_changed = Signal()
