import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.accounts.tests.helpers import PHONE, post, register_and_get_code, sign_in, verified_user
from apps.cart import services
from apps.cart.models import CartItem
from apps.cart.tests.helpers import lines, stocked, with_options
from apps.catalog.tests.helpers import make_product
from apps.wishlist.models import Favourite

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return verified_user()


def merge(user, items):
    services.merge_guest_cart(user, items)
    return lines(user)


# --- adding up ---------------------------------------------------------------------------------------------
def test_a_guest_cart_becomes_lines(user):
    mug, mug_variant = stocked("Mug")
    shirt, (small, medium) = with_options()
    result = merge(
        user,
        [
            {"product_id": mug.pk, "quantity": 2},
            {"product_id": shirt.pk, "quantity": 1, "variant_id": medium.pk},
        ],
    )
    assert result == [(mug_variant.pk, 2), (medium.pk, 1)]


def test_it_adds_to_what_the_account_already_has(user):
    mug, variant = stocked("Mug", stock=10)
    CartItem.objects.create(user=user, variant=variant, quantity=3)
    assert merge(user, [{"product_id": mug.pk, "quantity": 4}]) == [(variant.pk, 7)]


def test_the_same_variant_twice_is_added_up(user):
    mug, variant = stocked("Mug", stock=10)
    items = [
        {"product_id": mug.pk, "quantity": 2},
        {"product_id": mug.pk, "quantity": 3, "variant_id": variant.pk},  # the same variant, named this time
    ]
    assert merge(user, items) == [(variant.pk, 5)]


def test_a_missing_quantity_is_one_and_numeric_strings_are_read(user):
    mug, variant = stocked("Mug")
    assert merge(user, [{"product_id": str(mug.pk)}]) == [(variant.pk, 1)]
    assert merge(user, [{"product_id": mug.pk, "quantity": "2", "variant_id": str(variant.pk)}]) == [(variant.pk, 3)]


# --- the stock ceiling ---------------------------------------------------------------------------------
def test_the_total_is_capped_at_the_stock(user):
    mug, variant = stocked("Mug", stock=5)
    CartItem.objects.create(user=user, variant=variant, quantity=3)
    assert merge(user, [{"product_id": mug.pk, "quantity": 99}]) == [(variant.pk, 5)]


def test_a_new_line_is_capped_at_the_stock_too(user):
    mug, variant = stocked("Mug", stock=2)
    assert merge(user, [{"product_id": mug.pk, "quantity": 50}]) == [(variant.pk, 2)]


def test_an_out_of_stock_variant_is_skipped(user):
    mug, _ = stocked("Mug", stock=0)
    assert merge(user, [{"product_id": mug.pk, "quantity": 1}]) == []


def test_a_line_that_already_holds_more_than_the_stock_is_left_alone(user):
    mug, variant = stocked("Mug", stock=5)
    CartItem.objects.create(user=user, variant=variant, quantity=9)  # the stock dropped since
    assert merge(user, [{"product_id": mug.pk, "quantity": 2}]) == [(variant.pk, 9)]


# --- what is skipped -------------------------------------------------------------------------------------
def test_several_variants_and_none_chosen_is_skipped_but_the_rest_still_merge(user):
    shirt, _ = with_options()
    mug, mug_variant = stocked("Mug")
    result = merge(user, [{"product_id": shirt.pk, "quantity": 1}, {"product_id": mug.pk, "quantity": 1}])
    assert result == [(mug_variant.pk, 1)]


def test_a_variant_of_another_product_hidden_or_unknown_things_are_skipped(user):
    mug, mug_variant = stocked("Mug")
    other, other_variant = stocked("Other")
    hidden, hidden_variant = stocked("Hidden", is_active=False)
    off, off_variant = stocked("Off")
    off_variant.is_active = False
    off_variant.save()
    result = merge(
        user,
        [
            {"product_id": mug.pk, "quantity": 1, "variant_id": other_variant.pk},  # not mug's variant
            {"product_id": hidden.pk, "quantity": 1},
            {"product_id": off.pk, "quantity": 1},
            {"product_id": 424242, "quantity": 1},
            {"product_id": mug.pk, "quantity": 1, "variant_id": 424242},
        ],
    )
    assert result == []


@pytest.mark.parametrize(
    "garbage",
    [
        None,
        "text",
        7,
        [],
        {"product_id": None},
        {"quantity": 2},
        {"product_id": 0, "quantity": 1},
        {"product_id": -1, "quantity": 1},
        {"product_id": 1.5, "quantity": 1},
        {"product_id": True, "quantity": 1},
        {"product_id": "abc", "quantity": 1},
        {"product_id": 1, "quantity": 0},
        {"product_id": 1, "quantity": -3},
        {"product_id": 1, "quantity": "lots"},
        {"product_id": 1, "quantity": None},
        {"product_id": 1, "quantity": 1, "variant_id": "x"},
        {"product_id": 1, "quantity": 1, "variant_id": -4},
    ],
)
def test_garbage_never_raises_and_adds_nothing(user, garbage):
    stocked("Mug")  # product 1 may well exist
    assert merge(user, [garbage]) == []


def test_something_that_is_not_a_list_is_ignored(user):
    for junk in (None, "cart", {"product_id": 1}, 5):
        assert merge(user, junk) == []


def test_only_the_first_items_are_read(user, settings):
    settings.MAX_CART_LINES = 10_000
    products = [stocked(f"P{index}")[1] for index in range(services.MAX_MERGE_ITEMS + 5)]
    items = [{"product_id": variant.product_id, "quantity": 1} for variant in products]
    assert len(merge(user, items)) == services.MAX_MERGE_ITEMS


# --- the line limit -------------------------------------------------------------------------------------
def test_the_line_limit_is_respected_and_existing_lines_still_grow(user, settings):
    settings.MAX_CART_LINES = 2
    a, a_variant = stocked("A")
    b, b_variant = stocked("B")
    c, c_variant = stocked("C")
    CartItem.objects.create(user=user, variant=a_variant, quantity=1)
    result = merge(
        user,
        [{"product_id": c.pk, "quantity": 1}, {"product_id": a.pk, "quantity": 2}, {"product_id": b.pk, "quantity": 1}],
    )
    assert result == [(a_variant.pk, 3), (c_variant.pk, 1)]  # C came first and took the last place; B found none


# --- cost ---------------------------------------------------------------------------------------------
def test_the_number_of_queries_does_not_grow_with_the_guest_cart(user):
    def count(items):
        with CaptureQueriesContext(connection) as context:
            services.merge_guest_cart(user, items)
        return len(context)

    def entries(prefix, amount):
        return [{"product_id": stocked(f"{prefix}{i}")[0].pk, "quantity": 1} for i in range(amount)]

    small = count(entries("s", 2))
    assert count(entries("l", 30)) == small


# --- through the sign-in ------------------------------------------------------------------------------
def test_signing_in_merges_the_guests_cart_and_favourites(api_client, otp_outbox):
    mug, mug_variant = stocked("Mug", stock=3)
    liked = make_product("Liked")
    token, code = register_and_get_code(api_client, otp_outbox)

    response = sign_in(
        api_client,
        token,
        code,
        cart=[{"product_id": mug.pk, "quantity": 9}],
        favorite=[{"product_id": liked.pk}],
    )

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["tokens"]["access"] and body["tokens"]["refresh"]
    user_lines = CartItem.objects.values_list("variant_id", "quantity")
    assert list(user_lines) == [(mug_variant.pk, 3)]  # capped at the stock
    assert list(Favourite.objects.values_list("product_id", flat=True)) == [liked.pk]


def test_a_guest_cart_full_of_junk_never_blocks_the_sign_in(api_client, otp_outbox):
    stocked("Mug")
    token, code = register_and_get_code(api_client, otp_outbox)
    junk = [{"product_id": "x"}, {"quantity": 1}, {"product_id": 999999, "quantity": 2}, {"variant_id": {}}]
    response = sign_in(api_client, token, code, cart=junk, favorite=[{"nope": 1}, {"product_id": 999999}])
    assert response.status_code == 200
    assert CartItem.objects.count() == 0 and Favourite.objects.count() == 0


def test_a_failing_merge_never_blocks_the_sign_in(api_client, otp_outbox, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(services, "merge_guest_cart", broken)
    token, code = register_and_get_code(api_client, otp_outbox)
    assert sign_in(api_client, token, code, cart=[{"product_id": 1, "quantity": 1}]).status_code == 200


def test_a_second_sign_in_adds_to_the_cart_of_the_first(api_client, otp_outbox):
    mug, variant = stocked("Mug", stock=10)
    token, code = register_and_get_code(api_client, otp_outbox)
    sign_in(api_client, token, code, cart=[{"product_id": mug.pk, "quantity": 2}])

    login = post(api_client, "login", {"phone_number": PHONE}).json()["data"]["token"]
    sign_in(api_client, login, otp_outbox[-1].code, cart=[{"product_id": mug.pk, "quantity": 3}])

    assert list(CartItem.objects.values_list("variant_id", "quantity")) == [(variant.pk, 5)]
