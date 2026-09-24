import pytest
from django.db.models import Sum

from apps.cart.models import CartItem
from apps.catalog.models import Product, ProductVariant
from apps.catalog.tests.helpers import make_product
from apps.orders import services
from apps.orders.models import DeliveryCharge, Order, OrderItem, OrderSequence, OrderStatusHistory
from apps.orders.tests.helpers import (
    ORDERS,
    checkout_body,
    errors_of,
    line,
    lines,
    place,
    signed_in,
    stock_of,
    stocked,
    with_options,
)

pytestmark = pytest.mark.django_db


def snapshot():
    """Everything a successful order would have changed."""
    return {
        "orders": Order.objects.count(),
        "items": OrderItem.objects.count(),
        "history": OrderStatusHistory.objects.count(),
        "sequences": list(OrderSequence.objects.values_list("day", "last")),
        "stock": list(ProductVariant.objects.order_by("pk").values_list("pk", "stock_quantity")),
        "sold": list(Product.objects.order_by("pk").values_list("pk", "total_orders")),
        "carts": list(CartItem.objects.order_by("pk").values_list("user_id", "variant_id", "quantity")),
    }


def refused(client, *items, **overrides):
    """Place an order that must be a 400 and change nothing at all. Returns the `errors` list."""
    before = snapshot()
    response = place(client, *items, **overrides)
    errors = errors_of(response)
    assert snapshot() == before
    return errors


# --- the shape of the request ---------------------------------------------------------------------------------
def test_an_empty_items_list_is_a_400(api_client):
    response = api_client.post(ORDERS, checkout_body(), format="json")
    assert response.status_code == 400
    assert response.json()["errors"] == ["Items: This list may not be empty."]
    assert Order.objects.count() == 0


@pytest.mark.parametrize("items", [None, "text", {"product_id": 1}, 5])
def test_items_must_be_a_list(api_client, items):
    response = api_client.post(ORDERS, checkout_body(items=items), format="json")
    assert response.status_code == 400
    assert "items" in response.json()["field_errors"]


def test_items_is_required(api_client):
    body = checkout_body()
    del body["items"]
    assert "items" in api_client.post(ORDERS, body, format="json").json()["field_errors"]


def test_an_order_holds_a_limited_number_of_lines(api_client, settings):
    settings.MAX_CART_LINES = 2
    first, second, third = stocked("A")[0], stocked("B")[0], stocked("C")[0]
    assert place(api_client, line(first), line(second)).status_code == 201
    response = place(api_client, line(first), line(second), line(third))
    assert response.status_code == 400
    assert response.json()["errors"] == ["Items: An order can hold at most 2 different items."]
    assert Order.objects.count() == 1


@pytest.mark.parametrize(
    "item",
    [
        {},
        {"quantity": 1},
        {"product_id": 0, "quantity": 1},
        {"product_id": -3, "quantity": 1},
        {"product_id": "abc", "quantity": 1},
        {"product_id": 1},
        {"product_id": 1, "quantity": 0},
        {"product_id": 1, "quantity": -2},
        {"product_id": 1, "quantity": "many"},
        {"product_id": 1, "quantity": 10001},
        {"product_id": 1, "quantity": 1, "variant_id": 0},
        {"product_id": 1, "quantity": 1, "variant_id": "x"},
    ],
)
def test_a_bad_line_is_a_400_with_the_field_named(api_client, item):
    response = api_client.post(ORDERS, checkout_body(item), format="json")
    assert response.status_code == 400
    assert any(key.startswith("items") for key in response.json()["field_errors"])
    assert Order.objects.count() == 0


@pytest.mark.parametrize(
    "field, value",
    [
        ("name", ""),
        ("name", "   "),
        ("name", "x" * 151),
        ("name", None),
        ("email", "not-an-email"),
        ("phone_number", ""),
        ("phone_number", "01712345678"),
        ("phone_number", "+880171234567"),  # nine digits
        ("phone_number", "+88017123456789"),  # eleven digits
        ("phone_number", "+8801712 345678"),
        ("phone_number", "+8801712345abc"),
        ("phone_number", "+9101712345678"),
        ("phone_number", None),
        ("shipping_type", ""),
        ("shipping_type", "abroad"),
        ("shipping_type", None),
        ("shipping_address", ""),
        ("shipping_address", "   "),
        ("shipping_address", "x" * 501),
        ("shipping_address", None),
        ("payment_type", "card"),
        ("payment_type", "bkash"),
        ("payment_type", ""),
    ],
)
def test_a_bad_field_is_a_400_and_names_the_field(api_client, field, value):
    product, _ = stocked()
    response = api_client.post(ORDERS, checkout_body(line(product), **{field: value}), format="json")
    assert response.status_code == 400
    assert field in response.json()["field_errors"]
    assert Order.objects.count() == 0


@pytest.mark.parametrize("field", ["name", "phone_number", "shipping_type", "shipping_address"])
def test_a_required_field_may_not_be_missing(api_client, field):
    product, _ = stocked()
    body = checkout_body(line(product))
    del body[field]
    response = api_client.post(ORDERS, body, format="json")
    assert response.status_code == 400 and field in response.json()["field_errors"]


def test_the_error_is_shown_in_the_envelope_the_frontend_reads(api_client):
    product, _ = stocked()
    body = api_client.post(ORDERS, checkout_body(line(product), phone_number="123"), format="json").json()
    assert body["success"] is False and isinstance(body["errors"], list)
    assert body["error"] == body["errors"][0] == "Phone number: Enter a valid phone number: +880 followed by 10 digits."


def test_a_long_name_and_address_at_the_limit_are_fine(api_client):
    product, _ = stocked()
    assert place(api_client, line(product), name="n" * 150, shipping_address="a" * 500).status_code == 201


# --- shipping combinations ------------------------------------------------------------------------------------
def test_inside_dhaka_needs_the_area(api_client):
    product, _ = stocked()
    for area in ("", "   "):
        response = api_client.post(ORDERS, checkout_body(line(product), shipping_area=area), format="json")
        assert response.status_code == 400
        assert response.json()["field_errors"] == {"shipping_area": ["This field is required."]}
    body = checkout_body(line(product))
    del body["shipping_area"]
    assert "shipping_area" in api_client.post(ORDERS, body, format="json").json()["field_errors"]
    assert Order.objects.count() == 0


@pytest.mark.parametrize("missing", ["shipping_division", "shipping_district", "shipping_thana"])
def test_outside_dhaka_needs_division_district_and_thana(api_client, missing):
    product, _ = stocked()
    location = {"shipping_division": "Dhaka", "shipping_district": "Gazipur", "shipping_thana": "Sreepur"}
    location[missing] = ""
    response = api_client.post(
        ORDERS,
        checkout_body(line(product), shipping_type="outside_dhaka", shipping_area="", **location),
        format="json",
    )
    assert response.status_code == 400
    assert response.json()["field_errors"] == {missing: ["This field is required."]}


def test_outside_dhaka_with_nothing_filled_in_lists_all_three(api_client):
    product, _ = stocked()
    response = api_client.post(
        ORDERS, checkout_body(line(product), shipping_type="outside_dhaka", shipping_area=""), format="json"
    )
    assert set(response.json()["field_errors"]) == {"shipping_division", "shipping_district", "shipping_thana"}


# --- products and variants that can not be bought -----------------------------------------------------------
def test_an_unknown_product_is_refused(api_client):
    assert refused(api_client, {"product_id": 999999, "quantity": 1}) == ["Product 999999 is not available."]


def test_a_hidden_product_is_refused_without_revealing_its_name(api_client):
    product, variant = stocked("Secret Mug", is_active=False)
    errors = refused(api_client, line(product, variant))
    assert errors == [f"Product {product.pk} is not available."]


def test_a_product_without_variants_is_refused(api_client):
    bare = make_product("Bare")
    assert refused(api_client, line(bare)) == [f"Product {bare.pk} is not available."]


def test_an_inactive_variant_is_refused_and_does_not_count_as_a_choice(api_client):
    product, (small, medium) = with_options("Shirt", stocks=(5, 5))
    medium.is_active = False
    medium.save()
    assert refused(api_client, line(product, medium)) == ["Shirt: That colour or size is not available."]
    assert place(api_client, line(product)).status_code == 201  # only one active variant is left: no need to name it
    assert stock_of(small) == 4


def test_a_variant_of_another_product_is_refused(api_client):
    product, _ = stocked("One")
    _, foreign = stocked("Two")
    assert refused(api_client, line(product, foreign)) == ["One: That colour or size is not available."]


def test_several_variants_and_none_chosen_is_refused(api_client):
    product, _ = with_options("Shirt")
    assert refused(api_client, line(product)) == ["Shirt: Choose a colour or size first."]


# --- stock and minimum order quantity -----------------------------------------------------------------------
def test_out_of_stock_is_a_400(api_client):
    product, _ = stocked("Mug", stock=0)
    assert refused(api_client, line(product)) == ["Mug is out of stock."]


def test_asking_for_more_than_the_stock_is_a_400_and_writes_nothing(api_client):
    product, _ = stocked("Mug", stock=3)
    assert refused(api_client, line(product, quantity=4)) == ["Only 3 of Mug left in stock."]


def test_exactly_the_stock_is_fine(api_client):
    product, variant = stocked("Mug", stock=3)
    assert place(api_client, line(product, quantity=3)).status_code == 201
    assert stock_of(variant) == 0


def test_the_stock_check_uses_the_merged_quantity_of_a_variant(api_client):
    product, variant = stocked("Mug", stock=3)
    assert refused(api_client, line(product, variant, 2), line(product, variant, 2)) == ["Only 3 of Mug left in stock."]


def test_the_message_names_the_variant_when_there_are_options(api_client):
    product, (small, _) = with_options("Shirt", stocks=(1, 5))
    assert refused(api_client, line(product, small, 2)) == ["Only 1 of Shirt (Red / Size0-Shirt) left in stock."]


def test_below_the_minimum_order_quantity_is_a_400(api_client):
    product, _ = stocked("Mug", stock=10, minimum_order_quantity=3)
    assert refused(api_client, line(product, quantity=2)) == ["The minimum order for Mug is 3."]


def test_exactly_the_minimum_order_quantity_is_fine(api_client):
    product, variant = stocked("Mug", stock=10, minimum_order_quantity=3)
    assert place(api_client, line(product, quantity=3)).status_code == 201
    assert stock_of(variant) == 7


def test_the_minimum_is_checked_on_the_merged_line(api_client):
    product, variant = stocked("Mug", stock=10, minimum_order_quantity=2)
    assert place(api_client, line(product, variant, 1), line(product, variant, 1)).status_code == 201
    assert OrderItem.objects.get().quantity == 2


def test_the_minimum_applies_to_every_line_separately(api_client):
    shirt, (small, medium) = with_options("Shirt", stocks=(9, 9), minimum_order_quantity=2)
    errors = refused(api_client, line(shirt, small, 2), line(shirt, medium, 1))
    assert errors == ["The minimum order for Shirt (Red / Size1-Shirt) is 2."]


def test_the_cart_does_not_enforce_the_minimum_but_checkout_does():
    user, client = signed_in()
    product, variant = stocked(stock=10, minimum_order_quantity=5)
    CartItem.objects.create(user=user, variant=variant, quantity=1)  # the cart lets this through
    assert refused(client, line(product, variant, 1)) == ["The minimum order for Mug is 5."]
    assert lines(user) == [(variant.pk, 1)]


# --- every problem at once ------------------------------------------------------------------------------------
def test_every_problem_comes_back_together_in_the_order_found(api_client):
    gone, _ = stocked("Gone", is_active=False)
    sold_out, _ = stocked("Sold Out", stock=0)
    few, _ = stocked("Few", stock=2)
    picky, _ = stocked("Picky", stock=9, minimum_order_quantity=4)
    shirt, _ = with_options("Shirt")
    fine, fine_variant = stocked("Fine", stock=5)

    errors = refused(
        api_client,
        line(sold_out),
        line(gone),
        line(few, quantity=3),
        line(fine),
        line(picky, quantity=2),
        line(shirt),
        {"product_id": 424242, "quantity": 1},
    )

    assert sorted(errors) == sorted(
        [
            f"Product {gone.pk} is not available.",
            "Shirt: Choose a colour or size first.",
            "Product 424242 is not available.",
            "Sold Out is out of stock.",
            "Only 2 of Few left in stock.",
            "The minimum order for Picky is 4.",
        ]
    )
    # resolution problems come first (they are found before anything is locked), then the stock checks in line order
    assert errors[-3:] == [
        "Sold Out is out of stock.",
        "Only 2 of Few left in stock.",
        "The minimum order for Picky is 4.",
    ]
    assert stock_of(fine_variant) == 5  # the fine line was not sold either


def test_the_same_problem_is_reported_once(api_client):
    product, variant = stocked("Mug", stock=0)
    assert refused(api_client, line(product, variant), line(product, variant)) == ["Mug is out of stock."]


def test_a_bad_field_and_a_bad_line_are_not_mixed_up(api_client):
    """Field validation comes first; stock problems only show once the request itself is well formed."""
    product, _ = stocked("Mug", stock=0)
    response = api_client.post(ORDERS, checkout_body(line(product), phone_number="x"), format="json")
    assert response.json()["errors"] == ["Phone number: Enter a valid phone number: +880 followed by 10 digits."]


# --- delivery -------------------------------------------------------------------------------------------------
def test_a_missing_delivery_charge_is_a_400(api_client):
    product, _ = stocked()
    DeliveryCharge.objects.filter(shipping_type="inside_dhaka").delete()
    assert refused(api_client, line(product)) == ["Delivery is not available for this shipping type right now."]
    assert place(
        api_client,
        line(product),
        shipping_type="outside_dhaka",
        shipping_division="Dhaka",
        shipping_district="Gazipur",
        shipping_thana="Sreepur",
    ).status_code == 201  # the other type still works


def test_delivery_and_stock_problems_are_reported_together(api_client):
    product, _ = stocked("Mug", stock=0)
    DeliveryCharge.objects.all().delete()
    errors = refused(api_client, line(product))
    assert errors == ["Mug is out of stock.", "Delivery is not available for this shipping type right now."]


# --- nothing is written on failure, nothing is half written -----------------------------------------------------
def test_a_failed_order_leaves_stock_orders_counters_and_the_cart_untouched():
    user, client = signed_in()
    good, good_variant = stocked("Good", stock=5)
    bad, bad_variant = stocked("Bad", stock=1)
    CartItem.objects.create(user=user, variant=good_variant, quantity=2)
    CartItem.objects.create(user=user, variant=bad_variant, quantity=1)

    errors = refused(client, line(good, quantity=2), line(bad, quantity=2))

    assert errors == ["Only 1 of Bad left in stock."]
    assert lines(user) == [(good_variant.pk, 2), (bad_variant.pk, 1)]
    assert ProductVariant.objects.aggregate(total=Sum("stock_quantity"))["total"] == 6


def test_a_line_that_vanishes_between_the_read_and_the_lock_is_refused(api_client, monkeypatch):
    product, variant = stocked("Mug", stock=5)
    real = services._lock_variants

    def deactivating(ids, with_details=False):  # somebody hides the product while the order is being placed
        Product.objects.filter(pk=product.pk).update(is_active=False)
        return real(ids, with_details)

    monkeypatch.setattr(services, "_lock_variants", deactivating)
    assert refused(api_client, line(product, variant)) == ["Mug is no longer available."]


def test_a_deleted_variant_is_refused_by_its_name(api_client, monkeypatch):
    product, variant = stocked("Mug", stock=5)
    real = services._lock_variants

    def deleting(ids, with_details=False):
        ProductVariant.objects.filter(pk=variant.pk).delete()
        return real(ids, with_details)

    monkeypatch.setattr(services, "_lock_variants", deleting)
    assert refused(api_client, line(product, variant)) == ["Mug is no longer available."]


def test_the_stock_is_checked_after_the_lock_not_before(api_client, monkeypatch):
    """Somebody buys almost everything between our first read and the lock: the check must see the new number."""
    product, variant = stocked("Mug", stock=5)
    real = services._lock_variants

    def draining(ids, with_details=False):
        ProductVariant.objects.filter(pk=variant.pk).update(stock_quantity=1)
        return real(ids, with_details)

    monkeypatch.setattr(services, "_lock_variants", draining)
    assert refused(api_client, line(product, variant, 3)) == ["Only 1 of Mug left in stock."]
