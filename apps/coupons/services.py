"""Validating and redeeming a coupon. The only code that reads or writes a `Coupon` row for that purpose.

`apply_coupon_to_order` is called from `orders.services.place_order`, inside its own transaction, after the order's
real subtotal is known. Lock order (extends `orders.services`' own): variants, then products, then the coupon, then
the day's order counter — so a coupon lock never waits behind an order-counter lock or vice versa.

`release_coupon_usage` is called from `orders.services.change_status` when a coupon-bearing order is cancelled, the
same shape as `_restock()`: give back what a placed-then-undone order took.
"""
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.catalog.pricing import apply_discount
from apps.core.money import ZERO, quantize_money

from .models import Coupon


def _eligibility_problem(coupon, subtotal, phone_number):
    """One sentence, or None, for everything that does not need the database's own row lock to check."""
    now = timezone.now()
    if not coupon.is_active:
        return "This coupon is no longer active."
    if coupon.valid_from and now < coupon.valid_from:
        return "This coupon is not active yet."
    if coupon.valid_until and now > coupon.valid_until:
        return "This coupon has expired."
    if coupon.min_order_amount and subtotal < coupon.min_order_amount:
        return f"This coupon needs an order of at least {coupon.min_order_amount}."
    if coupon.max_redemptions is not None and coupon.times_used >= coupon.max_redemptions:
        return "This coupon is no longer available."
    if coupon.max_redemptions_per_customer is not None and phone_number:
        used = _customer_redemptions(coupon, phone_number)
        if used >= coupon.max_redemptions_per_customer:
            return "You have already used this coupon."
    return None


def _customer_redemptions(coupon, phone_number):
    """How many of this customer's non-cancelled orders already used this coupon."""
    from apps.orders.models import Order  # lazy: orders imports coupons, not the other way round

    return (
        Order.objects.filter(coupon=coupon, phone_number=phone_number)
        .exclude(status=Order.Status.CANCELLED)
        .count()
    )


def find_coupon(code):
    """The coupon for a code the customer typed (case/whitespace-insensitive), or None."""
    return Coupon.objects.filter(code=code.strip().upper()).first()


def validate_coupon(code, subtotal, phone_number=None):
    """The `Coupon` for `code` if it may be used against an order of `subtotal`, else a 400 `ValidationError`
    (one sentence). An unlocked read: `place_order` re-checks everything under the row lock before redeeming."""
    coupon = find_coupon(code)
    if coupon is None:
        raise ValidationError("This coupon code does not exist.")
    problem = _eligibility_problem(coupon, subtotal, phone_number)
    if problem:
        raise ValidationError(problem)
    return coupon


def compute_discount(coupon, subtotal):
    """How much `coupon` takes off `subtotal`: the catalog's own percentage/fixed rule, then capped so it never
    exceeds `max_discount_amount` or the subtotal itself."""
    subtotal = quantize_money(subtotal)
    after_discount = apply_discount(subtotal, coupon.discount_type, coupon.discount_value)
    discount = subtotal - after_discount
    if coupon.max_discount_amount is not None:
        discount = min(discount, quantize_money(coupon.max_discount_amount))
    return max(discount, ZERO)


def apply_coupon_to_order(code, subtotal, phone_number):
    """Re-validates `code` under the coupon's own row lock and counts one more use. Called only from inside
    `place_order`'s transaction, after the variant/product locks. Returns (coupon, discount_amount); raises the
    same `ValidationError` `validate_coupon` would, if the code stopped being valid between the preview and now."""
    coupon = Coupon.objects.select_for_update().filter(code=code.strip().upper()).first()
    if coupon is None:
        raise ValidationError("This coupon code does not exist.")
    problem = _eligibility_problem(coupon, subtotal, phone_number)
    if problem:
        raise ValidationError(problem)
    discount = compute_discount(coupon, subtotal)
    coupon.times_used += 1
    coupon.save(update_fields=["times_used"])
    return coupon, discount


def release_coupon_usage(coupon_id):
    """Give back one use of the coupon (never below 0) — the order that used it was cancelled."""
    if coupon_id is None:
        return
    coupon = Coupon.objects.select_for_update().filter(pk=coupon_id).first()
    if coupon is None:
        return
    coupon.times_used = max(coupon.times_used - 1, 0)
    coupon.save(update_fields=["times_used"])
