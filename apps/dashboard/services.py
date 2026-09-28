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
"""
from django.contrib.auth import get_user_model
from django.db.models import Count, Sum
from django.utils import timezone

from apps.catalog.models import Product, ProductVariant
from apps.coupons.models import Coupon
from apps.core.money import ZERO
from apps.orders.models import Order, OrderItem
from apps.payments.models import Payment

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
    return {
        "period": period,
        "period_label": PERIOD_LABELS[period],
        "periods": PERIOD_LABELS.items(),
        "revenue": revenue_summary(),
        "status_counts": order_status_counts(),
        "low_stock": low_stock_variants(low_stock_threshold),
        "low_stock_threshold": low_stock_threshold,
        "top_products": top_products(start_date),
        "coupons": coupon_summary(start_date),
        "new_customers": new_customers(start_date),
    }
