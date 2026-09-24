"""The cart rules in one place. Views stay thin; `receivers.merge_guest_cart_receiver` reuses `merge_guest_cart`.

- A line is a variant. `variant_id` may be left out when the product has exactly one (active) variant.
- POST adds or removes a *delta*; adding more than the stock is a 400 (nothing is reserved: stock is only taken
  when the order is placed). Removing down to 0 or below deletes the line.
- The minimum order quantity is NOT checked here: the frontend cart does not enforce it either, so it is checked
  when the order is placed.
- Lines whose product or variant was hidden stay in the database and reappear when it is visible again, but the
  cart does not show them.
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from rest_framework.exceptions import ValidationError

from apps.catalog.models import ProductVariant

from .models import CartItem

MAX_QUANTITY = 10_000
MAX_MERGE_ITEMS = 200


def _lock(user):
    """One cart writer at a time per customer: the line limit and the stock check can not be raced past."""
    get_user_model().objects.select_for_update().get(pk=user.pk)


def buyable_variants(product_id):
    """Active variants of a visible product, the default first."""
    return list(
        ProductVariant.objects.filter(product_id=product_id, is_active=True, product__is_active=True)
        .select_related("product", "color", "size")
        .order_by("-is_default", "id")
    )


def active_variants_by_product(product_ids):
    """{product_id: [active variants, the default first]} for visible products, in one query."""
    grouped = {}
    variants = ProductVariant.objects.filter(
        product_id__in=set(product_ids), is_active=True, product__is_active=True
    ).select_related("product", "color", "size")
    for variant in variants:  # ProductVariant's own ordering puts the default first
        grouped.setdefault(variant.product_id, []).append(variant)
    return grouped


def choose_variant(variants, variant_id=None):
    """(variant, None) or (None, why not), from the active variants of ONE product."""
    if not variants:
        return None, "This product is not available."
    if variant_id is not None:
        variant = next((v for v in variants if v.pk == variant_id), None)
        return (variant, None) if variant else (None, "That colour or size is not available.")
    if len(variants) == 1:
        return variants[0], None
    return None, "Choose a colour or size first."


def describe_variant(variant):
    """How a message names a line: Mug, or Shirt (Red / M) when the variant has options."""
    name = variant.product.name
    return f"{name} ({variant.label})" if variant.has_options else name


def add_to_cart(user, product_id, quantity, variant_id=None):
    """Put `quantity` more of a variant into the cart (`quantity` is a delta, not the new total)."""
    variant, problem = choose_variant(buyable_variants(product_id), variant_id)
    if problem:
        raise ValidationError(problem)
    with transaction.atomic():
        _lock(user)
        line = CartItem.objects.filter(user=user, variant=variant).first()
        current = line.quantity if line else 0
        stock = variant.stock_quantity
        if stock <= 0:
            raise ValidationError(f"{describe_variant(variant)} is out of stock.")
        if current + quantity > stock:
            already = f" (you already have {current} in your cart)" if current else ""
            raise ValidationError(f"Only {stock} of {describe_variant(variant)} left in stock{already}.")
        if line:
            line.quantity = current + quantity
            line.save(update_fields=["quantity", "updated_at"])
        else:
            if CartItem.objects.filter(user=user).count() >= settings.MAX_CART_LINES:
                raise ValidationError(f"Your cart can hold at most {settings.MAX_CART_LINES} different items.")
            CartItem.objects.create(user=user, variant=variant, quantity=quantity)


def decrease_in_cart(user, product_id, quantity, variant_id=None):
    """Take `quantity` off a line; 0 or less deletes it. A line that is not there is left alone (someone may
    have removed it in another tab), so the call is safe to repeat."""
    with transaction.atomic():
        _lock(user)
        lines = CartItem.objects.filter(user=user, variant__product_id=product_id)
        if variant_id is not None:
            lines = lines.filter(variant_id=variant_id)
        lines = list(lines[:2])
        if len(lines) > 1:
            raise ValidationError("Choose a colour or size first.")
        if not lines:
            return
        line = lines[0]
        if line.quantity - quantity <= 0:
            line.delete()
        else:
            line.quantity -= quantity
            line.save(update_fields=["quantity", "updated_at"])


def remove_from_cart(user, refs):
    """Delete lines. `refs` is [(product_id, variant_id | None)]: without a variant, every line of the product
    goes (the Checkout page sends only the product). Anything that is not in the cart is ignored."""
    condition = Q()
    for product_id, variant_id in refs:
        match = Q(variant__product_id=product_id)
        if variant_id is not None:
            match &= Q(variant_id=variant_id)
        condition |= match
    if condition:
        with transaction.atomic():
            CartItem.objects.filter(user=user).filter(condition).delete()


def cart_lines(user):
    """The visible lines, oldest first, with everything the cart page shows loaded."""
    return list(
        CartItem.objects.filter(user=user, variant__is_active=True, variant__product__is_active=True)
        .select_related("variant__product", "variant__color", "variant__size")
        .order_by("id")
    )


# --- merging a guest's browser cart at sign-in -------------------------------------------------------------
def _positive_int(raw, limit=None):
    if isinstance(raw, bool):
        return None
    if isinstance(raw, str) and raw.strip().isdigit():
        raw = int(raw)
    if isinstance(raw, int) and raw > 0:
        return min(raw, limit) if limit else raw
    return None


def merge_guest_cart(user, items):
    """Add the guest's browser cart to the customer's cart. `items` is untrusted (a list of
    `{product_id, quantity, variant_id?}`), and this must never stop a sign-in, so it is forgiving:

    - anything unusable is skipped: not a dict, unknown or hidden product, a variant of another product,
      several variants and none chosen;
    - the same variant twice is added up, and it is added to what the cart already holds;
    - the total is capped at the stock (an out-of-stock variant is skipped) and the line limit is respected.
    """
    if not isinstance(items, list):
        return
    wanted = {}
    for raw in items[:MAX_MERGE_ITEMS]:
        if not isinstance(raw, dict):
            continue
        product_id = _positive_int(raw.get("product_id"))
        quantity = _positive_int(raw.get("quantity", 1), MAX_QUANTITY)
        variant_id = raw.get("variant_id")
        if variant_id in (None, ""):
            variant_id = None
        else:
            variant_id = _positive_int(variant_id)
            if variant_id is None:
                continue
        if product_id is None or quantity is None:
            continue
        wanted[(product_id, variant_id)] = wanted.get((product_id, variant_id), 0) + quantity
    if not wanted:
        return

    by_product = active_variants_by_product(product_id for product_id, _ in wanted)

    to_add = {}
    for (product_id, variant_id), quantity in wanted.items():
        variant, problem = choose_variant(by_product.get(product_id, []), variant_id)
        if not problem:
            entry = to_add.setdefault(variant.pk, [variant, 0])
            entry[1] += quantity

    with transaction.atomic():
        _lock(user)
        lines = {line.variant_id: line for line in CartItem.objects.filter(user=user)}
        room = max(settings.MAX_CART_LINES - len(lines), 0)
        changed, created = [], []
        for variant, quantity in to_add.values():
            line = lines.get(variant.pk)
            current = line.quantity if line else 0
            target = min(current + quantity, variant.stock_quantity)
            if target <= current:
                continue  # out of stock, or the cart already holds as many as there are
            if line:
                line.quantity = target
                changed.append(line)
            elif room > 0:
                created.append(CartItem(user=user, variant=variant, quantity=target))
                room -= 1
        CartItem.objects.bulk_update(changed, ["quantity", "updated_at"])
        CartItem.objects.bulk_create(created)
