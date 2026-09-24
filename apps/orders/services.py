"""Orders: the only code that takes stock, sets prices and changes an order's status.

`place_order` (one `transaction.atomic()`):
  1. work out which variant each line means, add up the same variant listed twice;
  2. lock those variant rows (`select_for_update`, in pk order, so two orders that share variants can not
     deadlock) and only then check availability, stock and the minimum order quantity, so the numbers are the
     ones nobody else can change before we commit. Every problem is collected into ONE error, nothing is written;
  3. prices come from the database (`pricing.variant_prices`), the delivery charge from `DeliveryCharge`. Whatever
     prices and totals the client sent are never read;
  4. write the order, its lines (snapshots) and its first history row, take the stock, count the sale on each
     product, empty the customer's cart lines;
  5. take the order number LAST: the per-day counter row stays locked until the commit, so the less that happens
     after it the better.
Lock order everywhere is variants (pk order), then products (pk order), then the day counter.

`change_status` is the only place a status changes: it checks `state.py`, puts the goods back on the shelf when the
transition says so, and writes the `OrderStatusHistory` row.
"""
from collections import defaultdict

from django.conf import settings
from django.db import transaction
from django.db.models import Case, F, IntegerField, Value, When
from django.db.models.functions import Greatest
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError

from apps.addresses.models import Address
from apps.cart.models import CartItem
from apps.cart.services import active_variants_by_product, choose_variant, describe_variant
from apps.catalog.models import Product, ProductVariant
from apps.catalog.pricing import variant_prices
from apps.core.money import ZERO, quantize_money

from . import state
from .models import DeliveryCharge, Order, OrderItem, OrderSequence, OrderStatusHistory

# What the frontend calls the payment: its form sends "cash", its labels say "cod". Both are cash on delivery.
PAYMENT_TYPES = {"cash": Order.PaymentMethod.COD, "cod": Order.PaymentMethod.COD}


class InvalidTransition(APIException):
    """The order may not move from its status to the requested one (see `state.py`). A 400 if it ever reaches an API."""

    status_code = 400
    default_code = "invalid_transition"

    def __init__(self, old, new):
        self.old, self.new = old, new
        super().__init__(f"A {_status_label(old)} order can not become {_status_label(new)}.")


def _status_label(status):
    return Order.Status(status).label.lower() if status in Order.Status.values else str(status)


def _today():
    return timezone.localdate()  # Asia/Dhaka: the order counter restarts at local midnight


# --- shared helpers -------------------------------------------------------------------------------------------
def _lock_variants(variant_ids, with_details=False):
    """Lock the variant rows, ordered by pk (every writer of several variants does the same, so none can wait for
    another in a circle), and return {pk: variant}. Only the variant rows are locked (`of=("self",)`), not the joined
    product, colour and size. NO KEY UPDATE: enough to serialise the stock writers, yet a cart line (a foreign key to
    the variant) may still be inserted meanwhile."""
    variants = ProductVariant.objects.select_for_update(of=("self",), no_key=True)
    if with_details:
        variants = variants.select_related("product", "color", "size")
    return {variant.pk: variant for variant in variants.filter(pk__in=variant_ids).order_by("pk")}


def _shift_stock(quantities, direction):
    """Take (direction=-1) or return (+1) {variant_id: quantity} in ONE statement. The rows are already locked; the
    CHECK (stock_quantity >= 0) of the column is the backstop should a bug ever let the same unit be sold twice."""
    change = Case(
        *[When(pk=pk, then=Value(quantity)) for pk, quantity in quantities.items()], output_field=IntegerField()
    )
    stock = F("stock_quantity") + change if direction > 0 else F("stock_quantity") - change
    ProductVariant.objects.filter(pk__in=quantities).update(stock_quantity=stock, updated_at=timezone.now())


def _shift_total_orders(product_ids, direction):
    """`total_orders` (shown as "N orders") moves by one per distinct product: up when it is sold, down (never below
    0) when the order is given back. The rows are locked in pk order first, like the variants."""
    ids = sorted(set(product_ids))
    if not ids:
        return
    list(Product.objects.select_for_update(no_key=True).filter(pk__in=ids).order_by("pk").values_list("pk"))
    counter = F("total_orders") + 1 if direction > 0 else Greatest(F("total_orders") - 1, Value(0))
    Product.objects.filter(pk__in=ids).update(total_orders=counter)


def next_order_number():
    """`GC-20260923-0001`: prefix, the local date, a per-day counter (4 digits at least, it may grow past that).
    Must run inside `transaction.atomic()`: the day's counter row is locked until the commit."""
    today = _today()
    OrderSequence.objects.bulk_create([OrderSequence(day=today)], ignore_conflicts=True)  # first order of the day
    sequence = OrderSequence.objects.select_for_update().get(day=today)
    sequence.last += 1
    sequence.save(update_fields=["last"])
    return f"{settings.ORDER_NUMBER_PREFIX}-{today:%Y%m%d}-{sequence.last:04d}"


# --- placing an order -----------------------------------------------------------------------------------------
def _resolve_items(items, problems):
    """({variant_id: quantity}, {variant_id: variant}) in the order the customer listed them. A line without
    `variant_id` means the product's only active variant; the same variant listed twice is added up. The variants
    here are unlocked reads: they only tell which rows to lock (and name a line that vanishes in between)."""
    by_product = active_variants_by_product(item["product_id"] for item in items)
    wanted, named = {}, {}
    for item in items:
        variants = by_product.get(item["product_id"], [])
        variant, problem = choose_variant(variants, item.get("variant_id"))
        if problem:
            if variants:
                problems.append(f"{variants[0].product.name}: {problem}")
            else:
                problems.append(f"Product {item['product_id']} is not available.")
            continue
        wanted[variant.pk] = wanted.get(variant.pk, 0) + item["quantity"]
        named[variant.pk] = variant
    return wanted, named


def place_order(user=None, data=None):
    """Place an order for a signed-in `user` or a guest (`user=None`). `data` is a validated `PlaceOrderSerializer`
    dict. Returns the saved `Order`; raises a 400 `ValidationError` listing every problem, having written nothing."""
    items = data["items"]
    with transaction.atomic():
        problems = []
        wanted, named = _resolve_items(items, problems)

        delivery_charge = (
            DeliveryCharge.objects.filter(shipping_type=data["shipping_type"]).values_list("amount", flat=True).first()
        )

        lines = []  # (locked variant, quantity) of the lines that can be sold
        locked = _lock_variants(wanted, with_details=True) if wanted else {}
        for variant_id, quantity in wanted.items():
            variant = locked.get(variant_id)
            if variant is None or not (variant.is_active and variant.product.is_active):
                problems.append(f"{describe_variant(named[variant_id])} is no longer available.")
                continue
            name = describe_variant(variant)
            if variant.stock_quantity <= 0:
                problems.append(f"{name} is out of stock.")
            elif quantity > variant.stock_quantity:
                problems.append(f"Only {variant.stock_quantity} of {name} left in stock.")
            elif quantity < variant.product.minimum_order_quantity:
                problems.append(f"The minimum order for {name} is {variant.product.minimum_order_quantity}.")
            else:
                lines.append((variant, quantity))
        if delivery_charge is None:
            problems.append("Delivery is not available for this shipping type right now.")
        if problems:
            raise ValidationError(list(dict.fromkeys(problems)))  # each sentence once, in the order found

        rows, subtotal = [], ZERO
        for variant, quantity in lines:
            base_price, unit_price = variant_prices(variant)
            line_total = quantize_money(unit_price * quantity)
            subtotal += line_total
            rows.append(
                OrderItem(
                    product=variant.product,
                    variant=variant,
                    product_name=variant.product.name,
                    variant_label=variant.label,
                    sku=variant.sku,
                    unit_price=unit_price,
                    base_price=base_price,
                    quantity=quantity,
                    line_total=line_total,
                )
            )

        order = Order.objects.create(
            user=user,
            status=Order.Status.PENDING,
            name=data["name"],
            email=data.get("email") or "",
            phone_number=data["phone_number"],
            shipping_type=data["shipping_type"],
            shipping_area=data.get("shipping_area", ""),
            shipping_division=data.get("shipping_division", ""),
            shipping_district=data.get("shipping_district", ""),
            shipping_thana=data.get("shipping_thana", ""),
            shipping_address=data["shipping_address"],
            payment_method=PAYMENT_TYPES[data.get("payment_type", "cash")],
            subtotal=subtotal,
            delivery_charge=delivery_charge,
            total=subtotal + delivery_charge,
        )
        for row in rows:
            row.order = order
        OrderItem.objects.bulk_create(rows)
        OrderStatusHistory.objects.create(
            order=order, from_status="", to_status=order.status, changed_by=user, note="Order placed."
        )

        _shift_stock({variant.pk: quantity for variant, quantity in lines}, -1)
        _shift_total_orders((variant.product_id for variant, _ in lines), +1)
        if user is not None:
            CartItem.objects.filter(user=user, variant_id__in=[variant.pk for variant, _ in lines]).delete()

        order.number = next_order_number()  # last: see the module docstring
        order.save(update_fields=["number"])
    return order


# --- changing an order's status -------------------------------------------------------------------------------
def change_status(order, new_status, by=None, note=""):
    """Move `order` to `new_status` if `state.py` allows it, else raise `InvalidTransition`. The only place a status
    changes. Locks the order row (two staff members can not both cancel it and restock twice), puts the goods back
    when the transition says so, and writes the history row. `by` is the staff user, if any. Returns the order."""
    with transaction.atomic():
        locked = Order.objects.select_for_update().get(pk=order.pk)
        old = locked.status
        if not state.can_transition(old, new_status):
            raise InvalidTransition(old, new_status)
        if state.restocks(old, new_status):
            _restock(locked)
        locked.status = new_status
        locked.save(update_fields=["status", "updated_at"])
        OrderStatusHistory.objects.create(
            order=locked, from_status=old, to_status=new_status, changed_by=by, note=note
        )
    order.status, order.updated_at = locked.status, locked.updated_at  # the caller's copy is up to date too
    return order


def _restock(order):
    """Give the ordered quantities back and take the sale off each product's `total_orders`. A line whose variant or
    product was deleted from the catalog since (the links are SET_NULL) has nothing to go back to."""
    items = list(order.items.all())
    quantities = defaultdict(int)
    for item in items:
        if item.variant_id is not None:
            quantities[item.variant_id] += item.quantity
    if quantities:
        _lock_variants(quantities)
        _shift_stock(quantities, +1)
    _shift_total_orders((item.product_id for item in items if item.product_id is not None), -1)


# --- the checkout page ----------------------------------------------------------------------------------------
def checkout_content(user=None):
    """What `GET /content/checkout/` shows: the delivery charges, and for a signed-in customer their saved
    addresses (oldest first) and the details that pre-fill the form."""
    user_info = {"name": user.name, "phone_number": user.phone_number, "email": user.email or ""} if user else None
    return {
        "delivery_charges": {charge.shipping_type: charge.amount for charge in DeliveryCharge.objects.all()},
        "shipping_addresses": list(Address.objects.filter(user=user)) if user else [],
        "user_info": user_info,
    }
