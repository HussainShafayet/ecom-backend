"""Orders: the only code that takes stock, sets prices and changes an order's status.

`place_order` (one `transaction.atomic()`):
  1. work out which variant each line means, add up the same variant listed twice;
  2. lock those variant rows (`select_for_update`, in pk order, so two orders that share variants can not
     deadlock) and only then check availability, stock and the minimum order quantity, so the numbers are the
     ones nobody else can change before we commit. Every problem is collected into ONE error, nothing is written;
  3. prices come from the database (`pricing.variant_prices`), the delivery charge from `DeliveryCharge`. Whatever
     prices and totals the client sent are never read;
  4. a `coupon_code`, if any, is redeemed against the real subtotal above (`coupons.services.apply_coupon_to_order`,
     locking the coupon row) — again never against whatever discount the client showed;
  5. write the order, its lines (snapshots) and its first history row, take the stock, count the sale on each
     product, empty the customer's cart lines;
  6. take the order number LAST: the per-day counter row stays locked until the commit, so the less that happens
     after it the better (the stock history lines, which carry the number, are the one INSERT that follows it).
Lock order everywhere is variants (pk order), then the coupon, then products (pk order), then the day counter —
`change_status`'s cancellation path (below) releases the coupon before it restocks, for the same reason.

`change_status` is the only place a status changes: it checks `state.py`, puts the goods back on the shelf when the
transition says so, gives back the order's coupon use (if any) on a move to `CANCELLED` — so a customer who
cancels and retries is not blocked by their own cancelled attempt — and writes the `OrderStatusHistory` row.

Both announce themselves through `signals.py` (inside their transaction) so the payments app can follow along.
"""
import hashlib
import json
from collections import defaultdict
from datetime import timedelta

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Case, F, IntegerField, Value, When
from django.db.models.functions import Greatest
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, ValidationError

from apps.addresses.models import Address
from apps.cart.models import CartItem
from apps.cart.services import active_variants_by_product, choose_variant, describe_variant
from apps.catalog import stock
from apps.catalog.models import Product, ProductVariant, StockMovement
from apps.catalog.pricing import variant_prices
from apps.catalog.queries import main_images
from apps.core.money import ZERO, quantize_money
from apps.coupons import services as coupon_services

from . import hooks, signals, state
from .models import DeliveryCharge, Order, OrderItem, OrderRequestKey, OrderSequence, OrderStatusHistory

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


def _shift_stock(quantities, direction, field="stock_quantity"):
    """Take (direction=-1) or return (+1) {variant_id: quantity} in ONE statement. The rows are already locked; the
    CHECK (stock_quantity >= 0) of the column is the backstop should a bug ever let the same unit be sold twice.
    `field` is the counter that moves: the stock, or (for a damaged return) `damaged_quantity`."""
    change = Case(
        *[When(pk=pk, then=Value(quantity)) for pk, quantity in quantities.items()], output_field=IntegerField()
    )
    moved = F(field) + change if direction > 0 else F(field) - change
    ProductVariant.objects.filter(pk__in=quantities).update(**{field: moved, "updated_at": timezone.now()})


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

        delivery_charge, min_days, max_days = (
            DeliveryCharge.objects.filter(shipping_type=data["shipping_type"]).values_list("amount", "min_days", "max_days").first()
            or (None, None, None)
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

        coupon, discount_amount = None, ZERO
        if data.get("coupon_code"):
            coupon, discount_amount = coupon_services.apply_coupon_to_order(
                data["coupon_code"], subtotal, data["phone_number"]
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
            coupon=coupon,
            discount_amount=discount_amount,
            subtotal=subtotal,
            delivery_charge=delivery_charge,
            total=subtotal + delivery_charge - discount_amount,
            expected_from=timezone.localdate() + timedelta(days=min_days) if min_days is not None else None,
            expected_to=timezone.localdate() + timedelta(days=max_days) if max_days is not None else None,
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

        # Receivers (payments open the order's payment record) run BEFORE the number is taken, so the counter lock
        # stays the very last thing: see the module docstring. They must not need `order.number`.
        signals.order_placed.send(sender=Order, order=order)
        order.number = next_order_number()
        order.save(update_fields=["number"])
        stock.record(
            [(variant, -quantity, variant.stock_quantity - quantity, 0) for variant, quantity in lines],
            StockMovement.Kind.SALE,
            order.number,
            by=user,
        )
    return order


class KeyReused(APIException):
    """The `Idempotency-Key` was already used for a DIFFERENT order: answering it with the first one would hand the customer an order they did not
    ask for, and placing the second one would defeat the key. A 409."""

    status_code = 409
    default_code = "idempotency_key_reused"
    default_detail = "This Idempotency-Key was already used for a different order. Use a new key for a new order."


def _fingerprint(data):
    """A hash of what an order asks for (the validated body: the lines, the address, the coupon; whatever prices the client sent were dropped)."""
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def _lock_request_key(owner, key):
    """Hold a database lock, until this transaction ends, on one (owner, key): a second request with the SAME key waits here until the first has
    committed (then it finds its row) or rolled back (then it places the order itself). Requests with other keys do not wait for each other."""
    digest = hashlib.sha256(f"{owner}|{key}".encode()).digest()
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [int.from_bytes(digest[:8], "big", signed=True)])


def place_order_once(user, data, key):
    """`place_order`, safe to repeat under an `Idempotency-Key`. Returns `(order, replayed)`: `replayed` is True when this key had already placed an
    order for this customer (nothing is placed again: no stock taken, no coupon used, no message sent), a `KeyReused` when it was used for another
    order. See `OrderRequestKey`. The whole thing is one transaction, so a refused order (400) leaves no key behind."""
    owner = f"user:{user.pk}" if user is not None else f"guest:{data['phone_number']}"
    fingerprint = _fingerprint(data)
    with transaction.atomic():
        _lock_request_key(owner, key)
        earlier = OrderRequestKey.objects.select_related("order__coupon").filter(key=key, owner=owner).first()
        if earlier is not None:
            if earlier.fingerprint != fingerprint:
                raise KeyReused()
            return earlier.order, True
        order = place_order(user=user, data=data)
        OrderRequestKey.objects.create(key=key, owner=owner, fingerprint=fingerprint, order=order)
    return order, False


# --- changing an order's status -------------------------------------------------------------------------------
def change_status(order, new_status, by=None, note=""):
    """Move `order` to `new_status` if `state.py` allows it, else raise `InvalidTransition`. The only place a status
    changes. Locks the order row (two staff members can not both cancel it and restock twice), puts the goods back
    when the transition says so, gives back a coupon's use on a move to CANCELLED, and writes the history row.
    `by` is the staff user, if any. Returns the order."""
    with transaction.atomic():
        locked = Order.objects.select_for_update().get(pk=order.pk)
        old = locked.status
        if not state.can_transition(old, new_status):
            raise InvalidTransition(old, new_status)
        if new_status == Order.Status.CANCELLED and locked.coupon_id:
            coupon_services.release_coupon_usage(locked.coupon_id)
        if state.restocks(old, new_status):
            _restock(locked, by)
        locked.status = new_status
        locked.save(update_fields=["status", "updated_at"])
        OrderStatusHistory.objects.create(
            order=locked, from_status=old, to_status=new_status, changed_by=by, note=note
        )
        signals.order_status_changed.send(sender=Order, order=locked, old=old, new=new_status, by=by)
    order.status, order.updated_at = locked.status, locked.updated_at  # the caller's copy is up to date too
    return order


def _restock(order, by=None):
    """Give the ordered quantities back and take the sale off each product's `total_orders`, with a line in the stock history. A line
    whose variant or product was deleted from the catalog since (the links are SET_NULL) has nothing to go back to."""
    items = list(order.items.all())
    quantities = defaultdict(int)
    for item in items:
        if item.variant_id is not None:
            quantities[item.variant_id] += item.quantity
    if quantities:
        locked = _lock_variants(quantities, with_details=True)
        _shift_stock(quantities, +1)
        stock.record(
            [(locked[pk], quantities[pk], locked[pk].stock_quantity + quantities[pk], 0) for pk in sorted(locked)],
            StockMovement.Kind.RESTOCK,
            order.number,
            by=by,
        )
    _shift_total_orders((item.product_id for item in items if item.product_id is not None), -1)


def take_back_stock(good=None, damaged=None, reference="", by=None):
    """Goods a customer sent back and the shop has now received (the returns app calls this, inside its own transaction). `good` is
    `{variant_id: units}` that go back on the shelf; `damaged` is `{variant_id: units}` that can not be sold again: they are only counted in
    the variant's `damaged_quantity`, never added to the stock. The variants are locked in pk order like every other stock writer. Each
    variant gets one line in the stock history (`reference` names the return request, `by` is the staff user), damaged units included.
    Returns the variant ids that no longer exist (deleted from the catalog since the order): there is nothing to put those units back to."""
    good = {pk: units for pk, units in (good or {}).items() if units > 0}
    damaged = {pk: units for pk, units in (damaged or {}).items() if units > 0}
    wanted = set(good) | set(damaged)
    if not wanted:
        return set()
    locked = _lock_variants(wanted, with_details=True)
    existing = set(locked)
    if existing & set(good):
        _shift_stock({pk: units for pk, units in good.items() if pk in existing}, +1)
    if existing & set(damaged):
        _shift_stock({pk: units for pk, units in damaged.items() if pk in existing}, +1, field="damaged_quantity")
    stock.record(
        [
            (variant, good.get(pk, 0), variant.stock_quantity + good.get(pk, 0), damaged.get(pk, 0))
            for pk, variant in locked.items()
        ],
        StockMovement.Kind.RETURN,
        reference,
        by=by,
    )
    return wanted - existing


# --- what a customer sees of their orders --------------------------------------------------------------------
CANCEL_REFUSED = (
    "Only a pending order can be cancelled. To change an order that is already being handled, please contact us."
)


def customer_orders(user, statuses=None):
    """The signed-in customer's orders, newest first (a queryset, so it paginates); only those in `statuses` when some are given."""
    orders = Order.objects.filter(user=user).select_related("coupon").prefetch_related("items")
    return orders.filter(status__in=statuses) if statuses else orders


# While an order is on its way the customer is told when to expect it; once it has arrived, or will not, there is nothing to expect.
EXPECTING = (Order.Status.PENDING, Order.Status.CONFIRMED, Order.Status.PAID, Order.Status.SHIPPED)


def expected_delivery(order):
    """`{earliest, latest}` (dates) the customer was told to expect this order, or None: no estimate was promised, or the order is no
    longer on its way (delivered, cancelled, returned, refunded)."""
    if order.expected_from is None or order.expected_to is None or order.status not in EXPECTING:
        return None
    return {"earliest": order.expected_from, "latest": order.expected_to}


def customer_order(user, number):
    """One of the customer's own orders by its number, or a 404. An order of somebody else, a guest order and a
    number that does not exist all look the same."""
    order = (
        Order.objects.filter(user=user, number=number).select_related("coupon").prefetch_related("items", "history").first()
    )
    if order is None:
        raise NotFound("Order not found.")
    return order


def tracked_order(number, phone_number):
    """The order with this number, when `phone_number` is the one it was placed with. For a guest the pair is the key.
    Every miss is the same 404, so the answer never says which of the two was wrong."""
    order = (
        Order.objects.filter(number=number, phone_number=phone_number)
        .select_related("coupon")
        .prefetch_related("items", "history")
        .first()
    )
    if order is None:
        raise NotFound("No order matches these details.")
    return order


def order_extras(orders):
    """What the order serializers need besides the orders themselves, for a whole page in a fixed number of queries:
    the main image and slug of each ordered product, and each order's payment (from the payments app, if installed)."""
    orders = list(orders)
    product_ids = {item.product_id for order in orders for item in order.items.all() if item.product_id}
    slugs = dict(Product.objects.filter(pk__in=product_ids).values_list("pk", "slug")) if product_ids else {}
    images = main_images(product_ids) if product_ids else {}
    return {"images": images, "slugs": slugs, "payments": hooks.payment_info(orders)}


def cancel_order(user, number):
    """The customer cancels their own order. Only while it is pending (once it is paid or shipped a person has to
    decide); goes through `change_status`, so the goods go back on the shelf and the payment follows."""
    with transaction.atomic():
        order = Order.objects.select_for_update().filter(user=user, number=number).first()  # two clicks: one waits
        if order is None:
            raise NotFound("Order not found.")
        if order.status != Order.Status.PENDING:
            raise ValidationError(CANCEL_REFUSED)
        change_status(order, Order.Status.CANCELLED, by=user, note="Cancelled by the customer.")
    return customer_order(user, number)


# --- the checkout page ----------------------------------------------------------------------------------------
def checkout_content(user=None):
    """What `GET /content/checkout/` shows: the delivery charges, and for a signed-in customer their saved
    addresses (oldest first) and the details that pre-fill the form."""
    user_info = {"name": user.name, "phone_number": user.phone_number, "email": user.email or ""} if user else None
    charges = list(DeliveryCharge.objects.all())
    return {
        "delivery_charges": {charge.shipping_type: charge.amount for charge in charges},
        "delivery_estimates": {
            charge.shipping_type: {"min_days": charge.min_days, "max_days": charge.max_days}
            for charge in charges
            if charge.min_days is not None and charge.max_days is not None
        },
        "shipping_addresses": list(Address.objects.filter(user=user)) if user else [],
        "user_info": user_info,
    }
