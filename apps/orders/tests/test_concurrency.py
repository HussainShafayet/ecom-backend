"""Real simultaneous requests, one thread and one database connection each (like the cart's concurrency tests).
A transaction=True test commits for real, so the row locks are what is being tested, not a single connection's
snapshot."""
import threading

import pytest
from django.db import connection
from rest_framework.test import APIClient

from apps.orders import services
from apps.orders.models import Order, OrderItem
from apps.orders.tests.helpers import (
    errors_of,
    line,
    make_order,
    orders_of,
    place,
    stock_of,
    stocked,
    with_options,
)
from apps.orders.tests.test_place_order import today_number

pytestmark = pytest.mark.django_db(transaction=True)

PATIENCE = 60  # seconds: a deadlock would hang for ever, so waiting is bounded and then fails the test


def run_together(count, work):
    """Run `work(index)` in `count` threads that are released at the same moment; return the results in index order."""
    barrier = threading.Barrier(count)
    results, failures = [None] * count, []

    def runner(index):
        try:
            connection.ensure_connection()  # connect first, so the requests start together
            barrier.wait(timeout=PATIENCE)
            results[index] = work(index)
        except BaseException as exc:  # noqa: BLE001  (reported in the main thread)
            failures.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=runner, args=(index,)) for index in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=PATIENCE)
    assert not any(thread.is_alive() for thread in threads), "a thread is stuck: deadlock?"
    assert not failures, failures
    return results


def statuses(responses):
    return sorted(response.status_code for response in responses)


def test_two_orders_for_the_last_unit_let_exactly_one_win():
    product, variant = stocked("Mug", stock=1)

    responses = run_together(2, lambda _: place(APIClient(), line(product)))

    assert statuses(responses) == [201, 400]
    loser = next(response for response in responses if response.status_code == 400)
    assert errors_of(loser) == ["Mug is out of stock."]
    assert stock_of(variant) == 0
    assert Order.objects.count() == 1 and OrderItem.objects.count() == 1
    assert orders_of(product) == 1


def test_many_orders_at_once_never_sell_more_than_the_stock():
    product, variant = stocked("Mug", stock=5)

    responses = run_together(6, lambda _: place(APIClient(), line(product, quantity=2)))

    assert statuses(responses) == [201, 201, 400, 400, 400, 400]  # 5 units: two orders of 2, the rest are refused
    assert {tuple(errors_of(r)) for r in responses if r.status_code == 400} <= {
        ("Only 1 of Mug left in stock.",),
        ("Only 3 of Mug left in stock.",),
    }
    assert stock_of(variant) == 1
    assert sum(item.quantity for item in OrderItem.objects.all()) == 4


def test_orders_listing_the_same_variants_in_opposite_order_do_not_deadlock():
    first, first_variant = stocked("First", stock=100)
    second, second_variant = stocked("Second", stock=100)

    def work(index):
        items = [line(first), line(second)] if index % 2 == 0 else [line(second), line(first)]
        return place(APIClient(), *items)

    for _ in range(2):
        assert statuses(run_together(8, work)) == [201] * 8

    assert (stock_of(first_variant), stock_of(second_variant)) == (84, 84)
    assert (orders_of(first), orders_of(second)) == (16, 16)


def test_concurrent_orders_get_distinct_consecutive_numbers():
    products = [stocked(f"Product {index}", stock=5)[0] for index in range(10)]

    responses = run_together(10, lambda index: place(APIClient(), line(products[index])))

    numbers = [response.json()["data"]["order_id"] for response in responses]
    assert statuses(responses) == [201] * 10
    assert len(set(numbers)) == 10
    assert sorted(numbers) == [today_number(counter) for counter in range(1, 11)]  # no gaps either


def test_concurrent_orders_for_one_product_are_all_counted():
    """Different variants of one shirt, so nothing serialises the orders but the product's own counter."""
    shirt, variants = with_options("Shirt", stocks=(9, 9, 9, 9, 9, 9))

    responses = run_together(6, lambda index: place(APIClient(), line(shirt, variants[index])))

    assert statuses(responses) == [201] * 6
    assert orders_of(shirt) == 6  # no sale lost to a read-modify-write race


def test_two_simultaneous_cancels_give_the_goods_back_once():
    product, variant = stocked("Mug", stock=10)
    order = make_order(line(product, variant, 2))
    assert stock_of(variant) == 8

    def cancel(_):
        try:
            services.change_status(Order.objects.get(pk=order.pk), Order.Status.CANCELLED)
            return "cancelled"
        except services.InvalidTransition:
            return "refused"

    assert sorted(run_together(2, cancel)) == ["cancelled", "refused"]
    assert stock_of(variant) == 10
    assert orders_of(product) == 0
    assert order.history.count() == 2


def test_an_order_and_a_cancel_at_the_same_time_keep_the_stock_consistent():
    product, variant = stocked("Mug", stock=3)
    earlier = make_order(line(product, variant, 2))  # stock 1 left

    def work(index):
        if index == 0:
            services.change_status(Order.objects.get(pk=earlier.pk), Order.Status.CANCELLED)
            return 201
        return place(APIClient(), line(product, quantity=2)).status_code  # only fits once the cancel has returned 2

    results = run_together(2, work)

    assert results[0] == 201
    assert results[1] in (201, 400)
    expected = 3 - (2 if results[1] == 201 else 0)
    assert stock_of(variant) == expected
