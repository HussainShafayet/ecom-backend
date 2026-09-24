"""Placing an order costs the same number of queries however many lines it has (no query per line)."""
import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.cart.models import CartItem
from apps.orders.tests.helpers import line, place, signed_in, stocked, with_options

pytestmark = pytest.mark.django_db


def queries_for(client, *items):
    with CaptureQueriesContext(connection) as context:
        response = place(client, *items)
    assert response.status_code == 201, response.content
    return len(context)


def test_a_guest_order_costs_the_same_for_one_line_and_for_many(api_client):
    products = [stocked(f"P{index}", stock=50)[0] for index in range(13)]
    shirt, variants = with_options("Shirt", stocks=(50, 50, 50))
    one = queries_for(api_client, line(products[0]))
    many = queries_for(
        api_client, *[line(product) for product in products[1:]], *[line(shirt, variant) for variant in variants]
    )
    assert many == one
    assert one <= 18  # 15 today: a handful of statements, and none of them per line


def test_a_signed_in_order_costs_the_same_for_one_line_and_for_many():
    user, client = signed_in()
    products = [stocked(f"P{index}", stock=50)[0] for index in range(12)]
    for product in products:
        CartItem.objects.create(user=user, variant=product.variants.get(), quantity=1)
    one = queries_for(client, line(products[0]))
    many = queries_for(client, *[line(product) for product in products[1:]])
    assert many == one
