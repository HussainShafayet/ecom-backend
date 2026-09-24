"""What is locked, and in which order. A thread race can only show that a lock is there; that every writer takes them
in the same order (which is what rules out a deadlock) is checked here on the SQL itself."""
import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.orders import services
from apps.orders.models import Order
from apps.orders.tests.helpers import line, make_order, place, stocked

pytestmark = pytest.mark.django_db

VARIANTS = '"catalog_productvariant"'
PRODUCTS = '"catalog_product"'
PRODUCTS_BY_PK = 'SELECT "catalog_product"."id" AS "pk" FROM "catalog_product" WHERE "catalog_product"."id" IN'


def locking_statements(context):
    return [q["sql"] for q in context.captured_queries if " FOR " in q["sql"] and q["sql"].startswith("SELECT")]


def test_placing_an_order_locks_variants_then_products_then_the_day_counter(api_client):
    first, _ = stocked("First", stock=5)
    second, _ = stocked("Second", stock=5)

    with CaptureQueriesContext(connection) as context:
        assert place(api_client, line(second), line(first)).status_code == 201  # listed in the opposite order

    variants, products, counter = locking_statements(context)
    assert f"FROM {VARIANTS}" in variants and f"FOR NO KEY UPDATE OF {VARIANTS}" in variants
    assert f'ORDER BY {VARIANTS}."id" ASC' in variants  # pk order, whatever order the customer listed them in
    assert products.startswith(PRODUCTS_BY_PK) and " ORDER BY 1 ASC " in products  # column 1 is the id
    assert 'FROM "orders_ordersequence"' in counter and " FOR UPDATE" in counter


def test_the_number_is_taken_after_everything_else_is_written(api_client):
    product, _ = stocked(stock=5)

    with CaptureQueriesContext(connection) as context:
        place(api_client, line(product))

    statements = [q["sql"] for q in context.captured_queries]
    counter_lock = next(i for i, sql in enumerate(statements) if 'FROM "orders_ordersequence"' in sql and "FOR" in sql)
    after = [sql for sql in statements[counter_lock + 1 :] if not sql.startswith(("SAVEPOINT", "RELEASE"))]
    assert len(after) == 2  # bump the counter, store the number on the order: nothing else waits behind the lock
    assert after[0].startswith('UPDATE "orders_ordersequence"') and after[1].startswith('UPDATE "orders_order"')


def test_cancelling_locks_the_order_then_the_variants_then_the_products_then_the_payment():
    product, variant = stocked("Mug", stock=5)
    other, other_variant = stocked("Other", stock=5)
    order = make_order(line(other), line(product))

    with CaptureQueriesContext(connection) as context:
        services.change_status(order, Order.Status.CANCELLED)

    order_lock, variants, products, payment = locking_statements(context)
    assert 'FROM "orders_order"' in order_lock and " FOR UPDATE" in order_lock
    assert f'ORDER BY {VARIANTS}."id" ASC' in variants and f"FOR NO KEY UPDATE OF {VARIANTS}" in variants
    assert products.startswith(PRODUCTS_BY_PK) and " ORDER BY 1 ASC " in products
    # The payment follows the order's status, inside the same transaction, and is locked last: nothing in the other
    # code paths waits for a payment row while holding variants or products.
    assert 'FROM "payments_payment"' in payment and " FOR UPDATE" in payment
