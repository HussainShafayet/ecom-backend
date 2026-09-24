import importlib

import pytest
from django.apps import apps as django_apps

from apps.orders.models import Order
from apps.payments.models import Payment
from apps.payments.tests.helpers import placed

pytestmark = pytest.mark.django_db

migration = importlib.import_module("apps.payments.migrations.0002_backfill_payments")

EXPECTED = {
    "pending": ("pending", False, False),
    "shipped": ("pending", False, False),
    "paid": ("paid", True, False),
    "delivered": ("paid", True, False),
    "cancelled": ("cancelled", False, False),
    "refunded": ("refunded", True, True),
}


def test_orders_from_before_payments_get_the_payment_their_status_implies():
    orders = {}
    for status in EXPECTED:
        order, _ = placed(quantity=1, stock=50)
        Order.objects.filter(pk=order.pk).update(status=status)  # as if it had been in this status all along
        orders[status] = order
    Payment.objects.all().delete()  # they were placed before the payments app

    migration.backfill_payments(django_apps, None)

    assert Payment.objects.count() == len(EXPECTED)
    for status, (payment_status, collected, refunded) in EXPECTED.items():
        payment = Payment.objects.get(order=orders[status])
        assert payment.status == payment_status, status
        assert payment.method == "cod" and payment.amount == orders[status].total
        assert (payment.paid_at is not None) is collected, status
        assert (payment.refunded_at is not None) is refunded, status


def test_running_it_again_or_on_orders_that_have_one_changes_nothing():
    order, _ = placed()
    before = list(Payment.objects.values_list("pk", "status"))
    migration.backfill_payments(django_apps, None)
    migration.backfill_payments(django_apps, None)
    assert list(Payment.objects.values_list("pk", "status")) == before
    assert Payment.objects.filter(order=order).count() == 1


def test_every_order_status_is_covered_by_the_migration():
    assert set(migration.BY_ORDER_STATUS) == set(Order.Status.values)
