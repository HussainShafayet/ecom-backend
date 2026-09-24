"""Price rules in one place, shared by the API (step 5), the cart and `orders.services.place_order()`.

- A product has `base_price` plus an optional discount (`discount_type` percentage|fixed, `discount_value`).
- A variant may override the price: `base_price` (else the product's) and `discount_price` (an explicit final
  price; else the product's discount rule is applied to the variant's base price).
- The final price never goes below 0, and the client never sends one: the server always recomputes it.
"""
from apps.core.money import ZERO, quantize_money, to_decimal

PERCENTAGE = "percentage"
FIXED = "fixed"


def apply_discount(base_price, discount_type, discount_value):
    """Price after the discount rule, rounded to 2 places. No rule (or a zero value) leaves the price as is."""
    base = quantize_money(base_price)
    value = to_decimal(discount_value or 0)
    if not discount_type or value <= 0:
        return base
    if discount_type == PERCENTAGE:
        final = base - base * value / 100
    elif discount_type == FIXED:
        final = base - value
    else:
        raise ValueError(f"Unknown discount type: {discount_type!r}")
    return max(quantize_money(final), ZERO)


def product_prices(product):
    """(base_price, final_price) of the product itself."""
    base = quantize_money(product.base_price)
    return base, apply_discount(base, product.discount_type, product.discount_value)


def variant_prices(variant):
    """(base_price, final_price) that a customer pays for this variant."""
    product = variant.product
    base = quantize_money(variant.base_price if variant.base_price is not None else product.base_price)
    if variant.discount_price is not None:
        return base, quantize_money(variant.discount_price)
    return base, apply_discount(base, product.discount_type, product.discount_value)


def discount_price_error(variant_base_price, discount_price, product_base_price):
    """Message when an explicit variant discount price is higher than the price it discounts, else None."""
    base = variant_base_price if variant_base_price is not None else product_base_price
    if base is not None and discount_price is not None and discount_price > base:
        return "The discount price can not be higher than the price it discounts."
    return None
