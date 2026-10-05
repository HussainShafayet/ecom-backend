"""Read-only aggregations for the staff dashboard (admin > Dashboard). Nothing here writes anything, so the
transaction.atomic()/select_for_update() lock-ordering discipline that governs orders/coupons services.py does not
apply — every function below is a plain query against data other apps already own.

Revenue is defined as the sum of Payment.amount where Payment.status == PAID, bucketed by Payment.paid_at (not
Order.created_at): for cash on delivery, apps/payments/providers.py's CashOnDelivery.EFFECTS table is the source of
truth for when money actually moves — a payment becomes PAID when the order is marked paid or delivered, and moves
to CANCELLED/REFUNDED if the order is later cancelled/returned/refunded. Filtering on status == PAID is therefore
self-correcting: a payment that was collected and later refunded automatically drops out of every revenue figure
the next time the page loads, with no separate "subtract refunds" step. This means a past period's total can shift
if something in it is refunded later — that is intentional: the dashboard always shows real money currently held,
not a frozen historical figure.

Returns (apps/returns) are subtracted in their own line, not folded into revenue: "Refunded for returns" is the `refund_amount` of the
requests that are COMPLETED (the money was paid back), bucketed by `completed_at`, and "Net revenue" is revenue less that. Only requests of an
order whose payment is still PAID count: if staff also mark the whole order refunded its payment is already out of revenue, and its return
refund must not be taken off a second time. The courier cost the shop itself pays for returns (`courier_cost - return_charge`, bucketed by
`received_at`) is shown apart: with no cost price on a product there is no profit to take it from yet.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Count, DecimalField, Exists, F, OuterRef, Sum, Value
from django.db.models.functions import Greatest
from django.utils import timezone

from apps.catalog.models import Product, ProductVariant
from apps.coupons.models import Coupon
from apps.core.money import ZERO
from apps.orders.models import Order, OrderItem
from apps.payments.models import Payment
from apps.returns.models import ReturnItem, ReturnRequest

User = get_user_model()

LOW_STOCK_LIMIT = 20
TOP_PRODUCTS_LIMIT = 10
TOP_COUPONS_LIMIT = 5

PERIOD_LABELS = {"today": "Today", "week": "This week", "month": "This month", "all": "All time"}
# The business week is Saturday-Thursday (see apps/siteconfig's opening_hours help text), not the ISO Monday start.
_SATURDAY = 5  # Python's Monday=0 .. Sunday=6


def _period_start(period, today):
    if period == "today":
        return today
    if period == "week":
        return today - timezone.timedelta(days=(today.weekday() - _SATURDAY) % 7)
    if period == "month":
        return today.replace(day=1)
    return None  # "all"


def revenue_summary():
    """Today / this week / this month / all-time revenue, each a fresh aggregate (see module docstring)."""
    today = timezone.localdate()
    return {
        period: _revenue_since(_period_start(period, today))
        for period in ("today", "week", "month", "all")
    }


def _revenue_since(start_date):
    qs = Payment.objects.filter(status=Payment.Status.PAID)
    if start_date is not None:
        qs = qs.filter(paid_at__date__gte=start_date)
    return qs.aggregate(total=Sum("amount"))["total"] or ZERO


def refund_summary():
    """Today / this week / this month / all-time money paid back for returns, the same buckets as `revenue_summary`."""
    today = timezone.localdate()
    return {period: _refunds_since(_period_start(period, today)) for period in ("today", "week", "month", "all")}


def _refunds_since(start_date):
    paid = Payment.objects.filter(order=OuterRef("order"), status=Payment.Status.PAID)
    qs = ReturnRequest.objects.filter(status=ReturnRequest.Status.COMPLETED).filter(Exists(paid))
    if start_date is not None:
        qs = qs.filter(completed_at__date__gte=start_date)
    return qs.aggregate(total=Sum("refund_amount"))["total"] or ZERO


def returns_summary(start_date):
    """Returns whose goods came back since `start_date` (None for all-time): how many, how many units went back on the shelf and how many were
    damaged, and the courier cost the shop paid itself (what the customer did not pay of it). Plus the money paid back, see `refund_summary`."""
    received = ReturnRequest.objects.filter(status__in=(ReturnRequest.Status.RECEIVED, ReturnRequest.Status.COMPLETED))
    if start_date is not None:
        received = received.filter(received_at__date__gte=start_date)
    shop_cost = Greatest(F("courier_cost") - F("return_charge"), Value(ZERO), output_field=DecimalField(max_digits=12, decimal_places=2))
    units = ReturnItem.objects.filter(request__in=received).aggregate(good=Sum("good_quantity"), damaged=Sum("damaged_quantity"))
    return {
        "received": received.count(),
        "restocked_units": units["good"] or 0,
        "damaged_units": units["damaged"] or 0,
        "shop_courier_cost": received.aggregate(total=Sum(shop_cost))["total"] or ZERO,
        "refunded": _refunds_since(start_date),
    }


def order_status_counts():
    """How many orders are in each status right now (a live snapshot, not period-scoped). Every status is present,
    even with 0, so a status with no current orders still shows rather than being silently missing."""
    counts = dict.fromkeys(Order.Status.values, 0)
    counts.update(dict(Order.objects.values_list("status").annotate(n=Count("id")).values_list("status", "n")))
    return [{"status": status, "label": label, "count": counts[status]} for status, label in Order.Status.choices]


def low_stock_variants(threshold):
    """Active variants of active products at or below `threshold` units, lowest first."""
    return list(
        ProductVariant.objects.filter(
            is_active=True, product__is_active=True, stock_quantity__lte=threshold
        )
        .select_related("product", "color", "size")
        .order_by("stock_quantity")[:LOW_STOCK_LIMIT]
    )


def top_products(start_date):
    """The best-selling products (by units, with revenue alongside) among PAID payments since `start_date` (None
    for all-time). Ranked by units sold, not revenue: a Catalog/Order Manager cares more about sales volume than
    one large order skewing a revenue-sorted list."""
    qs = OrderItem.objects.filter(
        product_id__isnull=False,
        order__payments__status=Payment.Status.PAID,
    )
    if start_date is not None:
        qs = qs.filter(order__payments__paid_at__date__gte=start_date)
    rows = list(
        qs.values("product_id")
        .annotate(units=Sum("quantity"), revenue=Sum("line_total"))
        .order_by("-units")[:TOP_PRODUCTS_LIMIT]
    )
    products = Product.objects.in_bulk([row["product_id"] for row in rows])
    result = []
    for row in rows:
        product = products.get(row["product_id"])
        if product is None:  # the product was deleted since; skip rather than show a blank row
            continue
        result.append({"product": product, "units": row["units"], "revenue": row["revenue"] or ZERO})
    return result


def coupon_summary(start_date):
    """Coupon redemptions since `start_date` (None for all-time) plus the all-time top redeemed coupons."""
    qs = Order.objects.filter(coupon_id__isnull=False).exclude(status=Order.Status.CANCELLED)
    if start_date is not None:
        qs = qs.filter(created_at__date__gte=start_date)
    return {
        "redemptions": qs.count(),
        "top_coupons": list(Coupon.objects.filter(is_active=True).order_by("-times_used")[:TOP_COUPONS_LIMIT]),
    }


def new_customers(start_date):
    """Registered accounts created since `start_date` (None for all-time). Blind to guest checkouts (a guest order
    never creates a User row) — shown with a caveat in the template, not a reason to build guest-tracking."""
    qs = User.objects.all()
    if start_date is not None:
        qs = qs.filter(created_at__date__gte=start_date)
    return qs.count()


def dashboard_context(period, low_stock_threshold):
    if period not in PERIOD_LABELS:
        period = "month"
    today = timezone.localdate()
    start_date = _period_start(period, today)
    revenue, refunds = revenue_summary(), refund_summary()
    return {
        "period": period,
        "period_label": PERIOD_LABELS[period],
        "periods": PERIOD_LABELS.items(),
        "revenue": revenue,
        "refunds": refunds,
        "net_revenue": {key: revenue[key] - refunds[key] for key in revenue},
        "returns": returns_summary(start_date),
        "status_counts": order_status_counts(),
        "low_stock": low_stock_variants(low_stock_threshold),
        "low_stock_threshold": low_stock_threshold,
        "top_products": top_products(start_date),
        "coupons": coupon_summary(start_date),
        "new_customers": new_customers(start_date),
    }
