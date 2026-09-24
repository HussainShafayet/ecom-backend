"""`GET /orders/` (my orders) and `GET /orders/{order_id}/` (one of them)."""
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.catalog.tests.helpers import make_media
from apps.orders import services
from apps.orders.models import Order
from apps.accounts.tests.helpers import verified_user
from apps.orders.tests.helpers import ORDERS, line, make_order, signed_in, stocked

pytestmark = pytest.mark.django_db


def detail_url(order):
    return f"{ORDERS}{order.number}/"


def results(response):
    assert response.status_code == 200, response.content
    return response.json()["data"]["results"]


# --- who may read what -----------------------------------------------------------------------------------------
def test_a_guest_needs_a_token_for_the_list_and_for_an_order(api_client):
    product, _ = stocked()
    order = make_order(line(product))
    assert api_client.get(ORDERS).status_code == 401
    assert api_client.get(detail_url(order)).status_code == 401


def test_the_list_holds_only_my_orders_newest_first():
    me, client = signed_in("+8801711111111")
    other = verified_user("+8801722222222")
    product, _ = stocked(stock=50)
    first = make_order(line(product), user=me)
    make_order(line(product), user=other)
    make_order(line(product))  # a guest's
    second = make_order(line(product, quantity=2), user=me)

    rows = results(client.get(ORDERS))

    assert [row["order_id"] for row in rows] == [second.number, first.number]
    assert client.get(ORDERS).json()["data"]["count"] == 2


def test_somebody_elses_order_a_guest_order_and_an_unknown_number_are_all_the_same_404():
    me, client = signed_in("+8801711111111")
    other = verified_user("+8801722222222")
    product, _ = stocked(stock=50)
    theirs, guests = make_order(line(product), user=other), make_order(line(product))

    responses = [client.get(detail_url(theirs)), client.get(detail_url(guests)), client.get(f"{ORDERS}GC-19990101-0001/")]

    assert [response.status_code for response in responses] == [404, 404, 404]
    assert len({response.content for response in responses}) == 1  # nothing tells the three apart


def test_an_order_reads_the_same_with_and_without_the_trailing_slash():
    me, client = signed_in()
    product, _ = stocked()
    order = make_order(line(product), user=me)
    assert client.get(f"{ORDERS}{order.number}").status_code == 200
    assert client.get(f"{ORDERS}{order.number}/").status_code == 200


# --- the list ------------------------------------------------------------------------------------------------------
def test_a_row_of_the_list():
    me, client = signed_in()
    mug, _ = stocked("Mug", base_price="500.00", stock=50)
    lamp, _ = stocked("Lamp", base_price="200.00", stock=50)
    order = make_order(line(mug, quantity=2), line(lamp), user=me)

    (row,) = results(client.get(ORDERS))

    assert set(row) == {"order_id", "status", "status_display", "created_at", "total", "items_count", "items"}
    assert row["order_id"] == order.number
    assert (row["status"], row["status_display"]) == ("pending", "Pending")
    assert row["total"] == 1260.0  # 1000 + 200 + the 60 delivery charge
    assert row["items_count"] == 3  # units, not lines
    assert [(item["product_name"], item["quantity"]) for item in row["items"]] == [("Mug", 2), ("Lamp", 1)]


def test_the_list_is_paginated_like_the_product_lists():
    me, client = signed_in()
    product, _ = stocked(stock=100)
    numbers = [make_order(line(product), user=me).number for _ in range(5)]

    page = client.get(ORDERS, {"page_size": 2, "page": 2}).json()["data"]

    assert page["count"] == 5 and len(page["results"]) == 2
    assert [row["order_id"] for row in page["results"]] == list(reversed(numbers))[2:4]
    assert page["next"] and page["previous"]


def test_a_customer_without_orders_gets_an_empty_list():
    _, client = signed_in()
    assert client.get(ORDERS).json()["data"] == {"count": 0, "next": None, "previous": None, "results": []}


def test_the_list_costs_the_same_number_of_queries_for_one_order_and_for_many():
    me, client = signed_in()
    products = [stocked(f"P{n}", stock=100)[0] for n in range(4)]
    for product in products:
        make_media(product)

    def queries():
        with CaptureQueriesContext(connection) as context:
            assert client.get(ORDERS).status_code == 200
        return len(context)

    make_order(line(products[0]), user=me)
    one = queries()
    for _ in range(6):
        make_order(*[line(product) for product in products], user=me)

    assert queries() == one
    assert one <= 9


# --- one order --------------------------------------------------------------------------------------------------------
def test_an_order_in_full():
    me, client = signed_in("+8801711111111")
    product, variant = stocked("Mug", base_price="500.00", stock=50)
    media = make_media(product)
    order = make_order(line(product, variant, 2), user=me, name="Rahim Uddin", email="rahim@example.com")

    response = client.get(detail_url(order))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["order_id"] == order.number and data["status"] == "pending"
    assert (data["name"], data["email"], data["phone_number"]) == ("Rahim Uddin", "rahim@example.com", "+8801712345678")
    assert (data["shipping_type"], data["shipping_area"], data["shipping_address"]) == (
        "inside_dhaka",
        "Gulshan",
        "House 12, Road 5",
    )
    assert (data["subtotal"], data["delivery_charge"], data["total"]) == (1000.0, 60.0, 1060.0)
    (item,) = data["items"]
    assert (item["product_name"], item["variant_label"], item["quantity"]) == ("Mug", variant.label, 2)
    assert (item["unit_price"], item["base_price"], item["line_total"]) == (500.0, 500.0, 1000.0)
    assert item["product_id"] == product.pk and item["product_slug"] == product.slug
    assert item["image"] == f"http://testserver/media/{media.file.name}"  # absolute, the frontend is on another origin
    assert data["can_cancel"] is True


def test_the_payment_block_follows_the_payment():
    me, client = signed_in()
    product, _ = stocked()
    order = make_order(line(product), user=me)

    before = client.get(detail_url(order)).json()["data"]["payment"]
    services.change_status(order, Order.Status.SHIPPED)
    services.change_status(order, Order.Status.DELIVERED)
    after = client.get(detail_url(order)).json()["data"]["payment"]

    assert (before["method"], before["method_display"], before["status"], before["amount"], before["paid_at"]) == ("cod", "Cash on delivery", "pending", 1060.0, None)
    assert (after["status"], after["status_display"]) == ("paid", "Paid")
    assert after["paid_at"] is not None


def test_the_history_shows_the_statuses_and_when_but_not_who_or_the_staffs_note():
    me, client = signed_in()
    staff = verified_user("+8801799999999")
    product, _ = stocked()
    order = make_order(line(product), user=me)
    services.change_status(order, Order.Status.SHIPPED, by=staff, note="Courier Pathao, parcel 4471; customer was rude")

    history = client.get(detail_url(order)).json()["data"]["history"]

    assert [(step["status"], step["status_display"]) for step in history] == [("pending", "Pending"), ("shipped", "Shipped")]
    assert all(set(step) == {"status", "status_display", "created_at"} for step in history)
    assert "Pathao" not in client.get(detail_url(order)).content.decode()


@pytest.mark.parametrize(
    "status, expected",
    [("pending", True), ("paid", False), ("shipped", False)],
)
def test_can_cancel_is_true_only_while_the_order_is_pending(status, expected):
    me, client = signed_in()
    product, _ = stocked()
    order = make_order(line(product), user=me)
    if status == "paid":
        services.change_status(order, Order.Status.PAID)
    elif status == "shipped":
        services.change_status(order, Order.Status.SHIPPED)

    assert client.get(detail_url(order)).json()["data"]["can_cancel"] is expected


def test_a_deleted_product_leaves_the_snapshot_without_a_link_or_a_picture():
    me, client = signed_in()
    product, _ = stocked("Mug", base_price="500.00")
    make_media(product)
    order = make_order(line(product), user=me)
    product.delete()

    (item,) = client.get(detail_url(order)).json()["data"]["items"]

    assert (item["product_name"], item["unit_price"], item["quantity"]) == ("Mug", 500.0, 1)
    assert (item["product_id"], item["product_slug"], item["image"]) == (None, None, None)


def test_a_product_without_a_picture_has_no_image():
    me, client = signed_in()
    product, _ = stocked("Mug")
    order = make_order(line(product), user=me)
    assert client.get(detail_url(order)).json()["data"]["items"][0]["image"] is None


def test_prices_are_the_ones_paid_even_after_the_catalog_changes():
    me, client = signed_in()
    product, _ = stocked("Mug", base_price="500.00", stock=50)
    order = make_order(line(product), user=me)
    product.base_price = Decimal("900.00")
    product.save()

    data = client.get(detail_url(order)).json()["data"]

    assert (data["subtotal"], data["items"][0]["unit_price"]) == (500.0, 500.0)
