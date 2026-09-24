import threading

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.accounts.tests.helpers import authed_client, verified_user
from apps.cart.models import CartItem
from apps.cart.tests.helpers import CART, lines, signed_in, stocked, with_options
from apps.catalog import favourites
from apps.catalog.tests.helpers import make_color, make_media, make_product, make_size, make_variant
from apps.catalog.tests.test_api_products import ITEM_KEYS

pytestmark = pytest.mark.django_db

ITEM = ITEM_KEYS | {"quantity", "color_name", "color_hex_code", "size_name"}


def add(client, product, quantity=None, variant=None, action=None, **extra):
    body = {"product_id": product.pk, **extra}
    if quantity is not None:
        body["quantity"] = quantity
    if variant is not None:
        body["variant_id"] = variant.pk
    if action is not None:
        body["action"] = action
    return client.post(CART, body, format="json")


def error_of(response):
    assert response.status_code == 400, response.content
    body = response.json()
    assert body["success"] is False
    return body["error"]


# --- access ---------------------------------------------------------------------------------------------
def test_the_cart_needs_a_login(api_client):
    assert api_client.get(CART).status_code == 401
    assert api_client.post(CART, {"product_id": 1}, format="json").status_code == 401
    assert api_client.put(CART, {"product_id": 1}, format="json").status_code == 401


def test_both_slash_variants_resolve_without_redirect():
    _, client = signed_in()
    for path in ("/api/v1/accounts/cart", "/api/v1/accounts/cart/"):
        assert client.get(path).status_code == 200, path


# --- adding ---------------------------------------------------------------------------------------------
def test_adding_a_product_without_options_needs_no_variant_id():
    user, client = signed_in()
    product, variant = stocked()

    response = add(client, product, quantity=2, action="increase")

    assert response.status_code == 200
    assert response.json() == {"success": True, "message": "Your cart was updated.", "data": None}
    assert lines(user) == [(variant.pk, 2)]


def test_quantity_is_a_delta_and_adds_up():
    user, client = signed_in()
    product, variant = stocked()
    add(client, product, quantity=2, variant=variant)
    add(client, product, quantity=3, variant=variant, action="increase")
    assert lines(user) == [(variant.pk, 5)]


def test_quantity_and_action_default_to_one_and_increase():
    user, client = signed_in()
    product, variant = stocked()
    add(client, product)
    assert lines(user) == [(variant.pk, 1)]


def test_a_null_variant_id_counts_as_missing():
    user, client = signed_in()
    product, variant = stocked()
    response = client.post(CART, {"product_id": product.pk, "quantity": 1, "variant_id": None}, format="json")
    assert response.status_code == 200
    assert lines(user) == [(variant.pk, 1)]


def test_each_variant_is_its_own_line():
    user, client = signed_in()
    product, (small, medium) = with_options()
    add(client, product, variant=small)
    add(client, product, quantity=2, variant=medium)
    assert lines(user) == [(small.pk, 1), (medium.pk, 2)]


def test_carts_are_private():
    (mine, my_client), (other, _) = signed_in(), signed_in("+8801812345678")
    product, variant = stocked()
    add(my_client, product)
    assert lines(mine) == [(variant.pk, 1)]
    assert lines(other) == []


# --- which variant --------------------------------------------------------------------------------------
def test_several_variants_and_none_chosen_is_a_400():
    _, client = signed_in()
    product, _ = with_options()
    assert "Choose a colour or size" in error_of(add(client, product))


def test_a_variant_of_another_product_is_refused():
    user, client = signed_in()
    product, _ = stocked("One")
    _, foreign = stocked("Two")
    assert "not available" in error_of(add(client, product, variant=foreign))
    assert lines(user) == []


def test_an_inactive_variant_is_refused_and_does_not_count_as_a_choice():
    user, client = signed_in()
    product, (small, medium) = with_options()
    medium.is_active = False
    medium.save()
    assert "not available" in error_of(add(client, product, variant=medium))
    add(client, product)  # only one active variant is left, so none has to be named
    assert lines(user) == [(small.pk, 1)]


@pytest.mark.parametrize("kind", ["inactive", "unknown", "no variants"])
def test_a_product_that_can_not_be_bought_is_refused(kind):
    user, client = signed_in()
    if kind == "inactive":
        product, variant = stocked(is_active=False)
        response = add(client, product, variant=variant)
    elif kind == "unknown":
        response = client.post(CART, {"product_id": 999999, "quantity": 1}, format="json")
    else:
        response = add(client, make_product("Bare"))
    assert "not available" in error_of(response)
    assert lines(user) == []


# --- stock ----------------------------------------------------------------------------------------------
def test_out_of_stock_is_a_400():
    user, client = signed_in()
    product, _ = stocked("Mug", stock=0)
    assert "Mug is out of stock" in error_of(add(client, product))
    assert lines(user) == []


def test_asking_for_more_than_the_stock_is_a_400_and_changes_nothing():
    user, client = signed_in()
    product, variant = stocked("Mug", stock=3)
    add(client, product, quantity=2)

    message = error_of(add(client, product, quantity=2))

    assert "Only 3 of Mug left in stock" in message and "already have 2" in message
    assert lines(user) == [(variant.pk, 2)]


def test_exactly_the_stock_is_fine():
    user, client = signed_in()
    product, variant = stocked(stock=3)
    assert add(client, product, quantity=3).status_code == 200
    assert lines(user) == [(variant.pk, 3)]


def test_the_message_names_the_variant_when_there_are_options():
    _, client = signed_in()
    product, (small, _) = with_options("Shirt", stocks=(1, 5))
    assert "Shirt (Red / Size0-Shirt)" in error_of(add(client, product, quantity=2, variant=small))


def test_the_minimum_order_quantity_is_left_to_checkout():
    user, client = signed_in()
    product, variant = stocked(minimum_order_quantity=5)
    assert add(client, product, quantity=1).status_code == 200
    assert lines(user) == [(variant.pk, 1)]


# --- input ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"product_id": 0},
        {"product_id": "abc"},
        {"product_id": 1, "quantity": 0},
        {"product_id": 1, "quantity": -2},
        {"product_id": 1, "quantity": "many"},
        {"product_id": 1, "quantity": 10001},
        {"product_id": 1, "action": "remove"},
        {"product_id": 1, "variant_id": "x"},
        {"product_id": 1, "variant_id": 0},
    ],
)
def test_bad_input_is_a_400_with_the_field_named(body):
    _, client = signed_in()
    response = client.post(CART, body, format="json")
    assert response.status_code == 400
    assert response.json()["field_errors"]


def test_numeric_strings_are_accepted_like_the_frontends_form_data():
    user, client = signed_in()
    product, variant = stocked()
    body = {"product_id": str(product.pk), "quantity": "2", "variant_id": str(variant.pk)}
    response = client.post(CART, body, format="json")
    assert response.status_code == 200
    assert lines(user) == [(variant.pk, 2)]


def test_the_cart_holds_a_limited_number_of_lines(settings):
    settings.MAX_CART_LINES = 2
    user, client = signed_in()
    first, second, third = stocked("A")[0], stocked("B")[0], stocked("C")[0]
    add(client, first)
    add(client, second)
    assert "at most 2 different items" in error_of(add(client, third))
    assert add(client, first).status_code == 200  # more of a line it already has is fine
    assert len(lines(user)) == 2


# --- decreasing -----------------------------------------------------------------------------------------
def test_decrease_takes_off_a_delta():
    user, client = signed_in()
    product, variant = stocked()
    add(client, product, quantity=5)
    assert add(client, product, quantity=2, action="decrease").status_code == 200
    assert lines(user) == [(variant.pk, 3)]


@pytest.mark.parametrize("take", [3, 99])
def test_decreasing_to_zero_or_below_removes_the_line(take):
    user, client = signed_in()
    product, _ = stocked()
    add(client, product, quantity=3)
    add(client, product, quantity=take, action="decrease")
    assert lines(user) == []


def test_decreasing_a_line_that_is_not_there_is_a_harmless_no_op():
    user, client = signed_in()
    product, _ = stocked()
    assert add(client, product, action="decrease").status_code == 200
    assert lines(user) == []


def test_decrease_needs_the_variant_when_the_product_has_several_lines():
    user, client = signed_in()
    product, (small, medium) = with_options()
    add(client, product, quantity=2, variant=small)
    add(client, product, quantity=2, variant=medium)
    assert "Choose a colour or size" in error_of(add(client, product, action="decrease"))
    assert add(client, product, variant=medium, action="decrease").status_code == 200
    assert lines(user) == [(small.pk, 2), (medium.pk, 1)]


def test_decrease_does_not_need_stock_or_a_visible_product():
    user, client = signed_in()
    product, variant = stocked(stock=5)
    add(client, product, quantity=4)
    variant.stock_quantity = 0
    variant.save()
    product.is_active = False
    product.save()
    assert add(client, product, action="decrease", variant=variant).status_code == 200
    assert lines(user) == [(variant.pk, 3)]


# --- reading --------------------------------------------------------------------------------------------
def cart(client):
    response = client.get(CART)
    assert response.status_code == 200, response.content
    return response.json()["data"]


def test_an_empty_cart_is_an_empty_array():
    _, client = signed_in()
    assert cart(client) == []


def test_a_line_has_the_product_card_fields_plus_the_line_fields():
    _, client = signed_in()
    product, variant = stocked("Mug", stock=4, base_price="500.00", brand=None)
    add(client, product, quantity=2)

    (item,) = cart(client)

    assert set(item) == ITEM
    assert item["id"] == product.pk  # the PRODUCT id, as the frontend keys its cart
    assert item["variant_id"] == variant.pk
    assert item["quantity"] == 2
    assert (item["color_name"], item["color_hex_code"], item["size_name"]) == (None, None, None)
    assert item["availability_status"] is True


def test_a_line_shows_its_own_variants_price_colour_and_size():
    _, client = signed_in()
    product = make_product("Shirt", base_price="1000.00", discount_type="percentage", discount_value="10")
    red, blue = make_color("Red", "#FF0000"), make_color("Blue", "#0000FF")
    medium = make_size("M", 2)
    make_variant(product, color=red, stock_quantity=5)  # the default: the card would show this one
    dear = make_variant(product, color=blue, size=medium, stock_quantity=5, base_price="1200.00")
    add(client, product, variant=dear)

    (item,) = cart(client)

    assert (item["base_price"], item["discount_price"]) == (1200.0, 1080.0)
    assert item["has_discount"] is True
    assert (item["color_name"], item["color_hex_code"], item["size_name"]) == ("Blue", "#0000FF", "M")
    assert item["variant_id"] == dear.pk


def test_the_image_is_the_chosen_colours_picture_else_the_main_one():
    _, client = signed_in()
    product = make_product("Shirt")
    red, blue = make_color("Red", "#FF0000"), make_color("Blue", "#0000FF")
    shared = make_media(product, order=0)
    red_photo = make_media(product, color=red, order=1)
    red_line = make_variant(product, color=red, stock_quantity=5)
    blue_line = make_variant(product, color=blue, stock_quantity=5)
    add(client, product, variant=red_line)
    add(client, product, variant=blue_line)

    red_item, blue_item = cart(client)

    assert red_item["image"].endswith(red_photo.file.name)
    assert blue_item["image"].endswith(shared.file.name)  # Blue has no picture of its own


def test_lines_come_oldest_first_and_growing_a_line_does_not_move_it():
    _, client = signed_in()
    first, _ = stocked("First")
    second, _ = stocked("Second")
    add(client, first)
    add(client, second)
    add(client, first)
    assert [item["name"] for item in cart(client)] == ["First", "Second"]


def test_two_variants_of_one_product_are_two_entries():
    _, client = signed_in()
    product, (small, medium) = with_options()
    add(client, product, variant=small)
    add(client, product, variant=medium)
    items = cart(client)
    assert [item["id"] for item in items] == [product.pk, product.pk]
    assert [item["variant_id"] for item in items] == [small.pk, medium.pk]


def test_an_out_of_stock_line_says_so():
    _, client = signed_in()
    product, variant = stocked(stock=2)
    add(client, product, quantity=2)
    variant.stock_quantity = 0
    variant.save()
    assert cart(client)[0]["availability_status"] is False


def test_hidden_products_and_variants_leave_the_cart_view_but_come_back():
    user, client = signed_in()
    product, variant = stocked("Mug")
    other, other_variant = stocked("Other")
    add(client, product)
    add(client, other)

    product.is_active = False
    product.save()
    assert [item["name"] for item in cart(client)] == ["Other"]
    product.is_active = True
    product.save()
    assert [item["name"] for item in cart(client)] == ["Mug", "Other"]

    other_variant.is_active = False
    other_variant.save()
    assert [item["name"] for item in cart(client)] == ["Mug"]
    assert len(lines(user)) == 2  # nothing was deleted


def test_is_favourite_is_filled_from_the_wishlist(monkeypatch):
    _, client = signed_in()
    liked, _ = stocked("Liked")
    plain, _ = stocked("Plain")
    add(client, liked)
    add(client, plain)
    monkeypatch.setattr(favourites, "_providers", [lambda user, ids: {liked.pk} & set(ids)])
    assert {item["name"]: item["is_favourite"] for item in cart(client)} == {"Liked": True, "Plain": False}


def test_reading_costs_the_same_queries_however_many_lines():
    user, client = signed_in()

    def count():
        with CaptureQueriesContext(connection) as context:
            assert client.get(CART).status_code == 200
        return len(context)

    for index in range(2):
        product, _ = with_options(f"Small {index}")
        for variant in product.variants.all():
            CartItem.objects.create(user=user, variant=variant, quantity=1)
    small = count()
    for index in range(6):
        product, _ = with_options(f"Large {index}")
        make_media(product)
        for variant in product.variants.all():
            CartItem.objects.create(user=user, variant=variant, quantity=1)
    assert count() == small


# --- removing -------------------------------------------------------------------------------------------
def remove(client, body):
    return client.put(CART, body, format="json")


def test_removing_one_variant_leaves_the_others():
    user, client = signed_in()
    product, (small, medium) = with_options()
    add(client, product, variant=small)
    add(client, product, variant=medium)
    response = remove(client, {"product_id": product.pk, "variant_id": small.pk})
    assert response.status_code == 200
    assert response.json() == {"success": True, "message": "Removed from your cart.", "data": None}
    assert lines(user) == [(medium.pk, 1)]


def test_removing_a_product_without_a_variant_removes_all_its_lines():
    user, client = signed_in()
    product, (small, medium) = with_options()
    other, other_variant = stocked("Other")
    add(client, product, variant=small)
    add(client, product, variant=medium)
    add(client, other)
    remove(client, {"product_id": product.pk})
    assert lines(user) == [(other_variant.pk, 1)]


def test_removing_an_array_is_the_clear_all_of_the_cart_page():
    user, client = signed_in()
    product, (small, medium) = with_options()
    other, _ = stocked("Other")
    keep, keep_variant = stocked("Keep")
    for target, variant in ((product, small), (product, medium), (other, None)):
        add(client, target, variant=variant)
    add(client, keep)
    body = [
        {"product_id": product.pk, "variant_id": small.pk},
        {"product_id": product.pk, "variant_id": medium.pk},
        {"product_id": other.pk},  # the Checkout page sends no variant_id
    ]
    assert remove(client, body).status_code == 200
    assert lines(user) == [(keep_variant.pk, 1)]


def test_removing_what_is_not_there_is_fine_and_never_touches_other_carts():
    (mine, my_client), (other, other_client) = signed_in(), signed_in("+8801812345678")
    product, variant = stocked()
    add(other_client, product)
    assert remove(my_client, {"product_id": product.pk}).status_code == 200
    assert remove(my_client, [{"product_id": 424242, "variant_id": 1}]).status_code == 200
    assert lines(other) == [(variant.pk, 1)]


def test_removing_a_line_of_another_product_by_variant_id_does_nothing():
    user, client = signed_in()
    product, variant = stocked("One")
    other, _ = stocked("Two")
    add(client, product)
    remove(client, {"product_id": other.pk, "variant_id": variant.pk})  # the variant is not the other product's
    assert lines(user) == [(variant.pk, 1)]


@pytest.mark.parametrize(
    "body", ["text", 5, [1, 2], [{"variant_id": 3}], {"variant_id": 3}, {"product_id": 0}, [{"product_id": "x"}]]
)
def test_a_bad_removal_body_is_a_400(body):
    _, client = signed_in()
    assert remove(client, body).status_code == 400


def test_too_many_items_in_one_removal_is_a_400():
    _, client = signed_in()
    assert remove(client, [{"product_id": 1}] * 201).status_code == 400


def test_an_empty_array_removes_nothing():
    user, client = signed_in()
    product, variant = stocked()
    add(client, product)
    assert remove(client, []).status_code == 200
    assert lines(user) == [(variant.pk, 1)]


# --- two requests at once ----------------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
def test_two_simultaneous_adds_of_a_new_line_are_both_counted():
    user, _ = signed_in()
    product, variant = stocked(stock=100)
    statuses = []
    token = authed_client(user)._credentials["HTTP_AUTHORIZATION"]

    def worker():
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=token)
        try:
            statuses.append(add(client, product, quantity=2).status_code)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert statuses == [200] * 4
    assert lines(user) == [(variant.pk, 8)]


@pytest.mark.django_db(transaction=True)
def test_simultaneous_adds_can_not_pass_the_stock_together():
    user, _ = signed_in()
    product, variant = stocked(stock=3)
    statuses = []
    token = authed_client(user)._credentials["HTTP_AUTHORIZATION"]

    def worker():
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=token)
        try:
            statuses.append(add(client, product, quantity=2).status_code)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(statuses) == [200, 400, 400]
    assert lines(user) == [(variant.pk, 2)]


def test_a_cart_line_carries_the_products_minimum_order_quantity():
    """A cart line is a product card: the cart can warn about a quantity below the minimum before checkout refuses it."""
    user, client = signed_in()
    knives = make_product("Knife Set", minimum_order_quantity=3)
    variant = make_variant(knives, stock_quantity=10)
    assert add(client, knives, quantity=1, action="increase").status_code == 200  # the cart itself does not enforce it

    (line,) = client.get(CART).json()["data"]

    assert (line["quantity"], line["minimum_order_quantity"]) == (1, 3)
    assert lines(user) == [(variant.pk, 1)]
