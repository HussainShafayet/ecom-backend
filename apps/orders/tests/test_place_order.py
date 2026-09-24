from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.accounts.tests.helpers import verified_user
from apps.cart.models import CartItem
from apps.catalog.models import ProductVariant
from apps.catalog.tests.helpers import make_color, make_product, make_variant
from apps.orders import services
from apps.orders.models import Order, OrderItem, OrderSequence, OrderStatusHistory
from apps.orders.tests.helpers import (
    ORDERS,
    checkout_body,
    line,
    lines,
    make_order,
    orders_of,
    place,
    signed_in,
    stock_of,
    stocked,
    with_options,
)

pytestmark = pytest.mark.django_db


def today_number(counter=1):
    return f"GC-{timezone.localdate():%Y%m%d}-{counter:04d}"


# --- the happy path -----------------------------------------------------------------------------------------
def test_a_guest_places_an_order(api_client):
    product, variant = stocked("Mug", stock=10, base_price="500.00")

    response = place(api_client, line(product, variant, 2))

    assert response.status_code == 201
    body = response.json()
    assert (body["success"], body["message"]) == (True, "Order placed.")
    # `order_id` is what the frontend reads; the rest is what its confirmation page can show without another call.
    assert body["data"] == {
        "order_id": today_number(),
        "status": "pending",
        "created_at": body["data"]["created_at"],
        "subtotal": 1000.0,
        "delivery_charge": 60.0,
        "total": 1060.0,
    }
    order = Order.objects.get()
    assert parse_datetime(body["data"]["created_at"]) == order.created_at  # the same instant, written in Dhaka time
    assert order.number == today_number()
    assert order.user is None
    assert order.status == Order.Status.PENDING
    assert order.payment_method == Order.PaymentMethod.COD
    assert (order.subtotal, order.delivery_charge, order.total) == (
        Decimal("1000.00"),
        Decimal("60.00"),
        Decimal("1060.00"),
    )
    assert stock_of(variant) == 8
    assert orders_of(product) == 1


def test_the_order_keeps_a_snapshot_of_the_contact_and_the_lines(api_client):
    product, variant = stocked("Mug", stock=10, base_price="500.00")
    variant.sku = "MUG-RED"
    variant.save()

    place(api_client, line(product, variant, 2), name="Karim", email="k@example.com", shipping_address="Flat 4")

    order = Order.objects.get()
    assert (order.name, order.email, order.phone_number) == ("Karim", "k@example.com", "+8801712345678")
    assert (order.shipping_type, order.shipping_area, order.shipping_address) == ("inside_dhaka", "Gulshan", "Flat 4")
    item = order.items.get()
    assert (item.product, item.variant) == (product, variant)
    assert (item.product_name, item.variant_label, item.sku) == ("Mug", "Default", "MUG-RED")
    assert (item.unit_price, item.base_price, item.quantity, item.line_total) == (
        Decimal("500.00"),
        Decimal("500.00"),
        2,
        Decimal("1000.00"),
    )


def test_the_first_history_row_records_the_new_order(api_client):
    product, _ = stocked()
    place(api_client, line(product))
    row = OrderStatusHistory.objects.get()
    assert (row.from_status, row.to_status, row.changed_by, row.note) == ("", "pending", None, "Order placed.")


def test_a_signed_in_customer_gets_the_order_and_loses_the_ordered_cart_lines():
    user, client = signed_in()
    mug, mug_variant = stocked("Mug", stock=10)
    lamp, lamp_variant = stocked("Lamp", stock=10)
    shirt, (small, medium) = with_options("Shirt", stocks=(5, 5))
    for variant, quantity in ((mug_variant, 2), (lamp_variant, 1), (small, 1), (medium, 3)):
        CartItem.objects.create(user=user, variant=variant, quantity=quantity)

    response = place(client, line(mug, mug_variant, 2), line(shirt, medium, 3))

    assert response.status_code == 201
    order = Order.objects.get()
    assert order.user == user
    assert lines(user) == [(lamp_variant.pk, 1), (small.pk, 1)]  # only the ordered lines left the cart
    assert OrderStatusHistory.objects.get().changed_by == user


def test_another_customers_cart_is_never_touched():
    _, client = signed_in()
    other, _ = signed_in("+8801812345678")
    product, variant = stocked()
    CartItem.objects.create(user=other, variant=variant, quantity=1)
    place(client, line(product))
    assert lines(other) == [(variant.pk, 1)]


def test_a_guest_order_is_not_linked_to_an_account_with_the_same_phone(api_client):
    verified_user("+8801712345678")
    product, _ = stocked()
    place(api_client, line(product), phone_number="+8801712345678")
    assert Order.objects.get().user is None


def test_the_customer_may_order_for_a_different_name_and_phone():
    user, client = signed_in()
    product, _ = stocked()
    place(client, line(product), name="Someone Else", phone_number="+8801999999999")
    order = Order.objects.get()
    assert (order.user, order.name, order.phone_number) == (user, "Someone Else", "+8801999999999")


def test_ordering_the_last_unit_leaves_the_variant_out_of_stock(api_client):
    product, variant = stocked("Mug", stock=1)
    assert place(api_client, line(product)).status_code == 201
    assert stock_of(variant) == 0
    assert place(api_client, line(product)).status_code == 400


# --- prices are the server's ---------------------------------------------------------------------------------
def test_totals_use_discounted_and_variant_override_prices(api_client):
    # 1000 - 10% = 900 a piece
    shirt = make_product("Shirt", base_price="1000.00", discount_type="percentage", discount_value="10")
    plain = make_variant(shirt, stock_quantity=10)
    # a colour that overrides the price (1200 - 10% = 1080) and one that sets its final price (750.50)
    cap = make_product("Cap", base_price="1000.00", discount_type="percentage", discount_value="10")
    red, blue = make_color("Red", "#FF0000"), make_color("Blue", "#0000FF")
    dear = make_variant(cap, color=red, stock_quantity=10, base_price="1200.00")
    cheap = make_variant(cap, color=blue, stock_quantity=10, discount_price="750.50")

    response = place(
        api_client,
        line(shirt, plain, 2),
        line(cap, dear, 1),
        line(cap, cheap, 3),
        shipping_type="outside_dhaka",
        shipping_division="Dhaka",
        shipping_district="Gazipur",
        shipping_thana="Sreepur",
    )

    assert response.status_code == 201, response.content
    order = Order.objects.get()
    assert [(i.variant_id, i.unit_price, i.base_price, i.quantity, i.line_total) for i in order.items.all()] == [
        (plain.pk, Decimal("900.00"), Decimal("1000.00"), 2, Decimal("1800.00")),
        (dear.pk, Decimal("1080.00"), Decimal("1200.00"), 1, Decimal("1080.00")),
        (cheap.pk, Decimal("750.50"), Decimal("1000.00"), 3, Decimal("2251.50")),
    ]
    assert order.subtotal == Decimal("5131.50")
    assert order.delivery_charge == Decimal("120.00")  # outside Dhaka
    assert order.total == Decimal("5251.50")


def test_prices_and_totals_sent_by_the_client_are_ignored(api_client):
    product, variant = stocked("Mug", stock=10, base_price="500.00")

    response = place(
        api_client,
        line(product, variant, 2, price=1),
        sub_total_price="1.00",
        delivery_charge=0,
        total_price="1.00",
    )

    assert response.status_code == 201  # a mismatch is not an error
    order = Order.objects.get()
    assert (order.subtotal, order.delivery_charge, order.total) == (
        Decimal("1000.00"),
        Decimal("60.00"),
        Decimal("1060.00"),
    )
    assert order.items.get().unit_price == Decimal("500.00")


def test_the_delivery_charge_is_the_configured_one_and_old_orders_keep_theirs(api_client):
    from apps.orders.models import DeliveryCharge

    product, _ = stocked(stock=10, base_price="100.00")
    place(api_client, line(product))
    DeliveryCharge.objects.filter(shipping_type="inside_dhaka").update(amount=Decimal("80.00"))
    place(api_client, line(product))
    assert [o.delivery_charge for o in Order.objects.order_by("id")] == [Decimal("60.00"), Decimal("80.00")]
    assert [o.total for o in Order.objects.order_by("id")] == [Decimal("160.00"), Decimal("180.00")]


def test_later_catalog_edits_do_not_change_a_placed_order(api_client):
    product, variant = stocked("Mug", stock=10, base_price="500.00")
    place(api_client, line(product, variant))

    product.name = "Renamed"
    product.base_price = Decimal("999.00")
    product.save()

    item = OrderItem.objects.get()
    assert (item.product_name, item.unit_price) == ("Mug", Decimal("500.00"))


# --- lines and variants -------------------------------------------------------------------------------------
def test_a_variant_id_is_optional_when_the_product_has_one_variant(api_client):
    product, variant = stocked(stock=5)
    for extra in ({}, {"variant_id": None}):
        assert api_client.post(
            ORDERS, checkout_body({"product_id": product.pk, "quantity": 1, **extra}), format="json"
        ).status_code == 201
    assert OrderItem.objects.filter(variant=variant).count() == 2
    assert stock_of(variant) == 3


def test_a_product_with_options_is_ordered_by_variant_and_labelled(api_client):
    product, (small, medium) = with_options("Shirt", stocks=(5, 5))

    place(api_client, line(product, medium, 2))

    item = OrderItem.objects.get()
    assert item.variant == medium
    assert item.variant_label == "Red / Size1-Shirt"
    assert (stock_of(small), stock_of(medium)) == (5, 3)


def test_the_same_variant_listed_twice_becomes_one_line(api_client):
    product, variant = stocked("Mug", stock=10, base_price="100.00")

    response = place(api_client, line(product, variant, 2), line(product, None, 3))  # 2nd names no variant

    assert response.status_code == 201
    item = OrderItem.objects.get()
    assert (item.quantity, item.line_total) == (5, Decimal("500.00"))
    assert stock_of(variant) == 5


def test_two_variants_of_one_product_are_two_lines_but_one_sale_for_the_product(api_client):
    shirt, (small, medium) = with_options("Shirt", stocks=(9, 9))
    mug, _ = stocked("Mug")

    place(api_client, line(shirt, small, 2), line(shirt, medium, 3), line(mug))

    assert OrderItem.objects.count() == 3
    assert (orders_of(shirt), orders_of(mug)) == (1, 1)  # per order and product, not per unit or variant


def test_total_orders_counts_each_order_once_per_product(api_client):
    product, _ = stocked(stock=50)
    place(api_client, line(product, quantity=5))
    place(api_client, line(product, quantity=7))
    assert orders_of(product) == 2


def test_lines_come_back_in_the_order_they_were_listed(api_client):
    first, _ = stocked("First")
    second, _ = stocked("Second")
    place(api_client, line(second), line(first))
    assert [item.product_name for item in OrderItem.objects.order_by("id")] == ["Second", "First"]


# --- shipping and contact fields ----------------------------------------------------------------------------
def test_inside_dhaka_clears_the_outside_fields(api_client):
    product, _ = stocked()
    place(
        api_client,
        line(product),
        shipping_division="Sylhet",
        shipping_district="Sylhet",
        shipping_thana="Zakiganj",
    )
    order = Order.objects.get()
    assert (order.shipping_area, order.shipping_division, order.shipping_district, order.shipping_thana) == (
        "Gulshan",
        "",
        "",
        "",
    )


def test_outside_dhaka_keeps_division_district_thana_and_clears_the_area(api_client):
    product, _ = stocked()
    place(
        api_client,
        line(product),
        shipping_type="outside_dhaka",
        shipping_area="Gulshan",
        shipping_division="Sylhet",
        shipping_district="Sylhet",
        shipping_thana="Zakiganj",
    )
    order = Order.objects.get()
    assert order.shipping_type == "outside_dhaka"
    assert (order.shipping_area, order.shipping_division, order.shipping_district, order.shipping_thana) == (
        "",
        "Sylhet",
        "Sylhet",
        "Zakiganj",
    )
    assert order.delivery_charge == Decimal("120.00")


@pytest.mark.parametrize("payment_type", ["cash", "cod"])
def test_cash_and_cod_both_mean_cash_on_delivery(api_client, payment_type):
    product, _ = stocked()
    assert place(api_client, line(product), payment_type=payment_type).status_code == 201
    assert Order.objects.get().payment_method == "cod"


def test_payment_type_may_be_left_out(api_client):
    product, _ = stocked()
    body = checkout_body(line(product))
    del body["payment_type"]
    assert api_client.post(ORDERS, body, format="json").status_code == 201
    assert Order.objects.get().payment_method == "cod"


@pytest.mark.parametrize("email", ["", None])
def test_an_empty_or_null_email_is_stored_as_empty(api_client, email):
    product, _ = stocked()
    assert place(api_client, line(product), email=email).status_code == 201
    assert Order.objects.get().email == ""


def test_the_body_the_frontend_sends_works_as_it_is(api_client):
    """Extra keys (`shipping`, `sub_total_price`, ...) and numeric strings, like the Checkout page posts them."""
    product, variant = stocked(stock=5, base_price="100.00")
    item = {"product_id": str(product.pk), "variant_id": str(variant.pk), "quantity": "2", "price": "100"}
    body = checkout_body(item)
    assert api_client.post(ORDERS, body, format="json").status_code == 201
    assert Order.objects.get().total == Decimal("260.00")


def test_both_slash_variants_resolve_without_redirect(api_client):
    product, _ = stocked(stock=5)
    for path in ("/api/v1/orders", "/api/v1/orders/"):
        assert api_client.post(path, checkout_body(line(product)), format="json").status_code == 201, path


def test_a_guest_can_only_post_reading_the_list_needs_a_token(api_client):
    assert api_client.get(ORDERS).status_code == 401


def test_no_other_method_is_allowed_on_the_collection():
    _, client = signed_in()
    statuses = [client.put(ORDERS, {}, format="json").status_code, client.patch(ORDERS, {}, format="json").status_code]
    assert statuses + [client.delete(ORDERS).status_code] == [405, 405, 405]


# --- order numbers ------------------------------------------------------------------------------------------
def test_the_number_is_prefix_date_and_a_four_digit_counter(api_client):
    product, _ = stocked(stock=10)
    first = place(api_client, line(product)).json()["data"]["order_id"]
    second = place(api_client, line(product)).json()["data"]["order_id"]
    assert first == today_number(1) and second == today_number(2)
    assert first == f"GC-{timezone.localdate().strftime('%Y%m%d')}-0001"


def test_the_counter_restarts_every_day(api_client, monkeypatch):
    product, _ = stocked(stock=10)
    place(api_client, line(product))
    place(api_client, line(product))
    tomorrow = timezone.localdate() + timedelta(days=1)
    monkeypatch.setattr(services, "_today", lambda: tomorrow)

    number = place(api_client, line(product)).json()["data"]["order_id"]

    assert number == f"GC-{tomorrow:%Y%m%d}-0001"
    assert dict(OrderSequence.objects.values_list("day", "last")) == {timezone.localdate(): 2, tomorrow: 1}


def test_the_counter_may_grow_past_four_digits(api_client):
    product, _ = stocked(stock=10)
    OrderSequence.objects.create(day=timezone.localdate(), last=9999)
    assert place(api_client, line(product)).json()["data"]["order_id"] == today_number(10000)


def test_the_date_is_the_shops_local_date_not_utc(api_client, monkeypatch):
    """Asia/Dhaka is UTC+6: at 20:00 UTC on the 3rd it is already the 4th in Dhaka."""
    product, _ = stocked()
    monkeypatch.setattr(timezone, "now", lambda: datetime(2026, 9, 3, 20, 0, tzinfo=dt_timezone.utc))
    assert timezone.localdate() == date(2026, 9, 4)
    assert place(api_client, line(product)).json()["data"]["order_id"] == "GC-20260904-0001"


def test_the_prefix_comes_from_the_settings(api_client, settings):
    settings.ORDER_NUMBER_PREFIX = "SHOP"
    product, _ = stocked()
    assert place(api_client, line(product)).json()["data"]["order_id"] == f"SHOP-{timezone.localdate():%Y%m%d}-0001"


def test_the_number_is_safe_in_a_url(api_client):
    from urllib.parse import quote

    product, _ = stocked()
    number = place(api_client, line(product)).json()["data"]["order_id"]
    assert quote(number, safe="") == number


def test_a_failed_order_does_not_use_up_a_number(api_client):
    product, _ = stocked(stock=1)
    place(api_client, line(product, quantity=5))  # 400
    assert place(api_client, line(product)).json()["data"]["order_id"] == today_number(1)


# --- what a placed order leaves behind and what removing catalog data does --------------------------------------
def test_deleting_the_product_or_the_variant_keeps_the_order_and_its_snapshot(api_client):
    product, variant = stocked("Mug", base_price="500.00")
    place(api_client, line(product, variant))

    product.delete()  # what `seed_catalog --flush` does; the variant goes with it

    item = OrderItem.objects.get()
    assert (item.product, item.variant) == (None, None)
    assert (item.product_name, item.unit_price) == ("Mug", Decimal("500.00"))
    assert Order.objects.count() == 1


def test_deleting_the_customer_keeps_the_order():
    user, client = signed_in()
    product, _ = stocked()
    place(client, line(product))
    get_user_model().objects.filter(pk=user.pk).delete()
    order = Order.objects.get()
    assert order.user is None and order.name == "Rahim Uddin"


def test_the_service_returns_the_saved_order():
    product, variant = stocked(stock=3)
    order = make_order(line(product, variant, 2))
    assert order.pk and order.number == today_number()
    assert ProductVariant.objects.get(pk=variant.pk).stock_quantity == 1
