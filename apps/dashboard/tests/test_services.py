from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.tests.helpers import verified_user
from apps.catalog.tests.helpers import make_product, make_variant
from apps.coupons.tests.helpers import make_coupon
from apps.dashboard import services
from apps.orders.models import Order
from apps.orders.tests.helpers import line, make_order
from apps.payments.models import Payment
from apps.payments.tests.helpers import move, payment_of, placed

pytestmark = pytest.mark.django_db


# --- revenue ---------------------------------------------------------------------------------------------
def test_revenue_counts_a_paid_order_in_every_bucket_that_covers_today():
    order, _ = placed(quantity=2, price="500.00")  # subtotal 1000 + 60 delivery = 1060
    move(order, Order.Status.PAID)

    revenue = services.revenue_summary()

    assert revenue["today"] == revenue["week"] == revenue["month"] == revenue["all"] == Decimal("1060.00")


def test_revenue_ignores_a_payment_that_is_still_pending():
    placed(quantity=1, price="500.00")  # never moved past pending

    assert services.revenue_summary()["all"] == Decimal("0.00")


def test_revenue_from_last_month_is_excluded_from_today_this_week_and_this_month():
    order, _ = placed(quantity=1, price="500.00")
    move(order, Order.Status.PAID)
    payment = payment_of(order)
    Payment.objects.filter(pk=payment.pk).update(paid_at=timezone.now() - timezone.timedelta(days=40))

    revenue = services.revenue_summary()

    assert revenue["today"] == Decimal("0.00")
    assert revenue["week"] == Decimal("0.00")
    assert revenue["month"] == Decimal("0.00")
    assert revenue["all"] == Decimal("560.00")


def test_a_later_refund_removes_the_order_from_revenue():
    order, _ = placed(quantity=1, price="500.00")
    move(order, Order.Status.PAID, Order.Status.REFUNDED)

    assert services.revenue_summary()["all"] == Decimal("0.00")


# --- order status counts ----------------------------------------------------------------------------------
def test_every_status_is_present_even_with_zero_orders():
    counts = services.order_status_counts()

    assert {row["status"] for row in counts} == set(Order.Status.values)
    assert all(row["count"] == 0 for row in counts)


def test_status_counts_reflect_current_orders_only():
    placed(quantity=1)  # stays pending
    order, _ = placed(quantity=1)
    move(order, Order.Status.PAID)

    counts = {row["status"]: row["count"] for row in services.order_status_counts()}

    assert counts["pending"] == 1
    assert counts["paid"] == 1
    assert counts["delivered"] == 0


# --- low stock ---------------------------------------------------------------------------------------------
def test_low_stock_variants_respects_threshold_and_active_flags():
    low = make_variant(make_product("Low"), stock_quantity=3)
    high = make_variant(make_product("High"), stock_quantity=50)
    inactive_variant = make_variant(make_product("Inactive variant"), stock_quantity=1, is_active=False)
    inactive_product = make_product("Inactive product", is_active=False)
    make_variant(inactive_product, stock_quantity=1)

    variants = services.low_stock_variants(threshold=5)

    assert low in variants
    assert high not in variants
    assert inactive_variant not in variants
    assert not any(v.product_id == inactive_product.pk for v in variants)


# --- top products ------------------------------------------------------------------------------------------
def test_top_products_ranks_by_units_among_paid_orders_only():
    popular = make_product("Popular")
    popular_variant = make_variant(popular, stock_quantity=100)
    rare = make_product("Rare")
    rare_variant = make_variant(rare, stock_quantity=100)

    paid_order = make_order(line(popular, popular_variant, quantity=5))
    move(paid_order, Order.Status.PAID)
    still_pending = make_order(line(rare, rare_variant, quantity=9))  # not paid: must not count

    top = services.top_products(start_date=None)

    assert top[0]["product"] == popular
    assert top[0]["units"] == 5
    assert not any(row["product"] == rare for row in top)
    assert still_pending.status == Order.Status.PENDING


# --- coupons -----------------------------------------------------------------------------------------------
def test_coupon_summary_excludes_cancelled_redemptions():
    coupon = make_coupon(code="SAVE10")
    product = make_product("Mug")
    variant = make_variant(product, stock_quantity=10)

    kept = make_order(line(product, variant), coupon_code=coupon.code)
    cancelled = make_order(line(product, variant), coupon_code=coupon.code)
    move(cancelled, Order.Status.CANCELLED)

    summary = services.coupon_summary(start_date=None)

    assert summary["redemptions"] == 1
    assert kept.coupon_id == coupon.pk


# --- new customers -----------------------------------------------------------------------------------------
def test_new_customers_counts_registrations_since_start_date():
    from apps.accounts.models import User

    recent = verified_user("+8801711111111")
    old = verified_user("+8801722222222")
    User.objects.filter(pk=old.pk).update(created_at=timezone.now() - timezone.timedelta(days=40))

    today = timezone.localdate()

    assert services.new_customers(start_date=today) == 1
    assert services.new_customers(start_date=None) == 2
    assert recent.created_at is not None  # sanity: auto_now_add ran


# --- context assembly -------------------------------------------------------------------------------------
def test_an_unknown_period_falls_back_to_month():
    context = services.dashboard_context("not-a-real-period", low_stock_threshold=5)

    assert context["period"] == "month"
