import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.accounts.tests.helpers import authed_client, verified_user
from apps.catalog import favourites
from apps.catalog.models import Product
from apps.catalog.tests.helpers import (
    make_brand,
    make_category,
    make_color,
    make_media,
    make_product,
    make_size,
    make_tag,
    make_variant,
)

pytestmark = pytest.mark.django_db

LIST = "/api/v1/products/"
ITEM_KEYS = {
    "id", "name", "slug", "sku", "image", "base_price", "discount_price", "has_discount", "discount_type",
    "discount_value", "brand_name", "total_views", "total_orders", "total_reviews", "avg_rating",
    "availability_status", "has_variants", "variant_id", "is_favourite",
}  # fmt: skip


def get(client, query="", path=LIST):
    return client.get(f"{path}?{query}" if query else path)


def slugs(response):
    assert response.status_code == 200, response.content
    return [item["slug"] for item in response.json()["data"]["results"]]


def sellable(product, **variant):
    """Give the product one variant so it has stock and a variant id (every card needs one)."""
    variant.setdefault("stock_quantity", 5)
    make_variant(product, **variant)
    return product


# --- shape ---------------------------------------------------------------------------------------------
def test_list_item_has_exactly_the_fields_the_frontend_reads(api_client):
    brand = make_brand("Acme")
    product = sellable(
        make_product("Red Shirt", base_price="1000.00", discount_type="percentage", discount_value="10", brand=brand)
    )
    make_media(product)

    body = get(api_client).json()

    assert body["success"] is True
    assert body["data"]["count"] == 1
    item = body["data"]["results"][0]
    assert set(item) == ITEM_KEYS
    assert item["image"].startswith("http://testserver/media/products/")
    assert item["brand_name"] == "Acme"
    assert item["has_discount"] is True
    assert item["discount_type"] == "percentage"
    assert item["availability_status"] is True
    assert item["has_variants"] is False
    assert item["variant_id"] == product.variants.get().pk
    assert item["is_favourite"] is False


def test_money_is_a_number_never_a_string(api_client):
    sellable(make_product(base_price="999.99", discount_type="percentage", discount_value="15"))
    item = get(api_client).json()["data"]["results"][0]
    for key in ("base_price", "discount_price", "discount_value", "avg_rating"):
        assert isinstance(item[key], (int, float)), key
    assert item["base_price"] == 999.99
    assert item["discount_price"] == 849.99


def test_without_a_discount_the_discount_price_equals_the_base_price(api_client):
    sellable(make_product(base_price="250.00"))
    item = get(api_client).json()["data"]["results"][0]
    assert item["discount_price"] == item["base_price"] == 250.0
    assert item["has_discount"] is False
    assert item["discount_type"] is None
    assert item["discount_value"] == 0


def test_a_variant_price_override_shows_on_the_card(api_client):
    product = make_product(base_price="1000.00", discount_type="fixed", discount_value="100")
    make_variant(product, base_price="1200.00", stock_quantity=1)
    item = get(api_client).json()["data"]["results"][0]
    assert (item["base_price"], item["discount_price"]) == (1200.0, 1100.0)


def test_a_product_without_image_brand_or_variants_still_renders(api_client):
    make_product("Bare")
    item = get(api_client).json()["data"]["results"][0]
    assert item["image"] is None
    assert item["brand_name"] is None
    assert item["variant_id"] is None
    assert item["availability_status"] is False


def test_has_variants_when_a_colour_or_size_has_to_be_chosen(api_client):
    product = make_product()
    make_variant(product, size=make_size("M"))
    assert get(api_client).json()["data"]["results"][0]["has_variants"] is True


def test_public_and_both_slash_variants_answer_without_redirect(api_client):
    sellable(make_product())
    for path in ("/api/v1/products", "/api/v1/products/"):
        response = api_client.get(path)
        assert response.status_code == 200, path


# --- visibility, default order, pagination ---------------------------------------------------------------
def test_inactive_products_are_hidden(api_client):
    make_product("Shown")
    make_product("Hidden", is_active=False)
    assert slugs(get(api_client)) == ["shown"]


def test_default_order_is_newest_first(api_client):
    for name in ("First", "Second", "Third"):
        make_product(name)
    assert slugs(get(api_client)) == ["third", "second", "first"]


def test_pagination_count_next_previous(api_client):
    for index in range(5):
        make_product(f"P{index}")
    data = get(api_client, "page_size=2&page=2").json()["data"]
    assert data["count"] == 5
    assert len(data["results"]) == 2
    assert data["next"] and "page=3" in data["next"]
    assert data["previous"]


def test_a_page_past_the_end_is_empty_not_an_error(api_client):
    make_product("Only")
    response = get(api_client, "page=9")
    assert response.status_code == 200
    assert response.json()["data"]["results"] == []


def test_page_size_is_capped(api_client):
    make_product("Only")
    assert get(api_client, "page_size=100000").status_code == 200


# --- filters ---------------------------------------------------------------------------------------------
def test_category_includes_its_child_categories(api_client):
    clothing = make_category("Clothing")
    shirts = make_category("Shirts", parent=clothing)
    shoes = make_category("Shoes")
    in_child = make_product("In child")
    in_child.categories.add(shirts)
    in_root = make_product("In root")
    in_root.categories.add(clothing)
    elsewhere = make_product("Elsewhere")
    elsewhere.categories.add(shoes)

    assert set(slugs(get(api_client, "category=clothing"))) == {"in-child", "in-root"}
    assert slugs(get(api_client, "category=shirts")) == ["in-child"]
    assert slugs(get(api_client, "category=shoes")) == ["elsewhere"]


def test_unknown_or_hidden_category_matches_nothing(api_client):
    hidden = make_category("Hidden", is_active=False)
    make_product("P").categories.add(hidden)
    assert slugs(get(api_client, "category=hidden")) == []
    assert slugs(get(api_client, "category=nope")) == []


def test_a_product_in_two_matching_categories_is_listed_once(api_client):
    clothing = make_category("Clothing")
    shirts = make_category("Shirts", parent=clothing)
    product = make_product("Both")
    product.categories.add(clothing, shirts)
    response = get(api_client, "category=clothing")
    assert slugs(response) == ["both"]
    assert response.json()["data"]["count"] == 1


def test_brands_are_comma_separated_and_case_insensitive(api_client):
    acme, zed, other = make_brand("Acme"), make_brand("Zed"), make_brand("Other")
    make_product("A", brand=acme)
    make_product("Z", brand=zed)
    make_product("O", brand=other)
    assert set(slugs(get(api_client, "brands=acme,ZED"))) == {"a", "z"}
    assert slugs(get(api_client, "brands=Other")) == ["o"]
    assert slugs(get(api_client, "brands=nobody")) == []


def test_tags_filter(api_client):
    eco, sale = make_tag("eco"), make_tag("sale")
    tagged = make_product("Tagged")
    tagged.tags.add(eco, sale)
    make_product("Plain")
    assert slugs(get(api_client, "tags=SALE")) == ["tagged"]
    assert slugs(get(api_client, "tags=eco,sale")) == ["tagged"]  # once, although two tags match


def test_colors_and_sizes_must_match_the_same_variant(api_client):
    red, blue = make_color("Red", "#FF0000"), make_color("Blue", "#0000FF")
    small, medium = make_size("S", 1), make_size("M", 2)
    shirt = make_product("Shirt")
    make_variant(shirt, color=red, size=small)
    make_variant(shirt, color=blue, size=medium)
    other = make_product("Other")
    make_variant(other, color=red, size=medium)

    assert set(slugs(get(api_client, "colors=Red"))) == {"shirt", "other"}
    assert set(slugs(get(api_client, "sizes=M"))) == {"shirt", "other"}
    assert slugs(get(api_client, "colors=red&sizes=s")) == ["shirt"]  # a red one and a size S one are not enough
    assert slugs(get(api_client, "colors=Red,Blue&sizes=M")) == ["other", "shirt"]
    assert slugs(get(api_client, "colors=Blue&sizes=S")) == []


def test_inactive_variants_do_not_count_for_colors_and_sizes(api_client):
    red = make_color("Red", "#FF0000")
    shirt = make_product("Shirt")
    make_variant(shirt, color=red, is_active=False)
    assert slugs(get(api_client, "colors=Red")) == []


def test_price_range_uses_what_the_customer_pays(api_client):
    make_product("Cheap", base_price="100.00")
    make_product("Discounted", base_price="1000.00", discount_type="percentage", discount_value="50")  # pays 500
    make_product("Dear", base_price="900.00")
    assert slugs(get(api_client, "min_price=400&max_price=600")) == ["discounted"]
    assert set(slugs(get(api_client, "min_price=500"))) == {"discounted", "dear"}
    assert slugs(get(api_client, "min_price=600")) == ["dear"]  # "Discounted" costs 1000 before, 500 after
    assert set(slugs(get(api_client, "max_price=500"))) == {"cheap", "discounted"}
    assert slugs(get(api_client, "min_price=500.00&max_price=500.00")) == ["discounted"]  # bounds are inclusive


def test_discount_type_and_value_are_an_exact_match(api_client):
    make_product("Ten percent", base_price="500", discount_type="percentage", discount_value="10")
    make_product("Ten fixed", base_price="500", discount_type="fixed", discount_value="10")
    make_product("Twenty percent", base_price="500", discount_type="percentage", discount_value="20")
    make_product("None")
    assert slugs(get(api_client, "discount_type=percentage&discount_value=10")) == ["ten-percent"]
    assert slugs(get(api_client, "discount_type=fixed&discount_value=10")) == ["ten-fixed"]
    assert set(slugs(get(api_client, "discount_type=percentage"))) == {"ten-percent", "twenty-percent"}
    assert set(slugs(get(api_client, "discount_value=10"))) == {"ten-percent", "ten-fixed"}


def test_search_looks_in_name_sku_model_brand_and_tags(api_client):
    make_product("Blue Denim Jacket", sku="JK-1")
    make_product("Plain", sku="ZX-99")
    make_product("With model", sku="M-1", model="Aurora 5")
    make_product("Branded", sku="B-1", brand=make_brand("Levi"))
    tagged = make_product("Tagged", sku="T-1")
    tagged.tags.add(make_tag("vintage"))

    assert slugs(get(api_client, "search=denim")) == ["blue-denim-jacket"]
    assert slugs(get(api_client, "search=zx-99")) == ["plain"]
    assert slugs(get(api_client, "search=aurora")) == ["with-model"]
    assert slugs(get(api_client, "search=levi")) == ["branded"]
    assert slugs(get(api_client, "search=VINTAGE")) == ["tagged"]


def test_search_words_must_all_match(api_client):
    make_product("Blue Denim Jacket")
    make_product("Blue Cotton Shirt")
    assert slugs(get(api_client, "search=blue jacket")) == ["blue-denim-jacket"]
    assert slugs(get(api_client, "search=jacket blue")) == ["blue-denim-jacket"]
    assert slugs(get(api_client, "search=blue")) == ["blue-cotton-shirt", "blue-denim-jacket"]


def test_search_treats_percent_and_underscore_literally(api_client):
    make_product("Plain shirt")
    make_product("50% Cotton")
    assert slugs(get(api_client, "search=%")) == ["50-cotton"]
    assert slugs(get(api_client, "search=_")) == []


def test_filters_combine_with_and(api_client):
    acme = make_brand("Acme")
    make_product("Match", base_price="100", brand=acme)
    make_product("Wrong brand", base_price="100", brand=make_brand("Other"))
    make_product("Too dear", base_price="900", brand=acme)
    assert slugs(get(api_client, "brands=Acme&max_price=500")) == ["match"]


def test_blank_and_unknown_parameters_are_ignored(api_client):
    make_product("P")
    assert slugs(get(api_client, "min_price=&brands=&search=&ordering=&colors=&whatever=1")) == ["p"]


@pytest.mark.parametrize(
    "query", ["ordering=bogus", "min_price=abc", "max_price=-5", "discount_type=percent", "discount_value=x"]
)
def test_bad_parameters_are_a_400_with_the_field_named(api_client, query):
    response = get(api_client, query)
    assert response.status_code == 400
    body = response.json()
    assert body["success"] is False
    assert body["field_errors"]


# --- ordering --------------------------------------------------------------------------------------------
@pytest.fixture
def priced():
    """cheap: pays 100, base 100 · mid: pays 300, base 600 (50% off) · dear: pays 900, base 900."""
    make_product("Cheap", base_price="100.00", avg_rating="4.5")
    make_product("Mid", base_price="600.00", discount_type="percentage", discount_value="50", avg_rating="2.0")
    make_product("Dear", base_price="900.00", avg_rating="3.0")


def test_ordering_by_price_is_before_the_discount(api_client, priced):
    assert slugs(get(api_client, "ordering=price")) == ["cheap", "mid", "dear"]
    assert slugs(get(api_client, "ordering=-price")) == ["dear", "mid", "cheap"]


def test_ordering_by_discount_price_is_what_the_customer_pays(api_client, priced):
    assert slugs(get(api_client, "ordering=discount_price")) == ["cheap", "mid", "dear"]
    assert slugs(get(api_client, "ordering=-discount_price")) == ["dear", "mid", "cheap"]
    make_product("Bargain", base_price="1000.00", discount_type="fixed", discount_value="950")  # pays 50
    assert slugs(get(api_client, "ordering=discount_price"))[0] == "bargain"
    assert slugs(get(api_client, "ordering=price"))[-1] == "bargain"  # but its price before the discount is highest


def test_ordering_by_rating(api_client, priced):
    assert slugs(get(api_client, "ordering=rating")) == ["mid", "dear", "cheap"]
    assert slugs(get(api_client, "ordering=-rating")) == ["cheap", "dear", "mid"]


def test_equal_sort_keys_fall_back_to_newest_first_so_pages_are_stable(api_client):
    for name in ("A", "B", "C", "D"):
        make_product(name, base_price="100.00")
    first = slugs(get(api_client, "ordering=price&page_size=2&page=1"))
    second = slugs(get(api_client, "ordering=price&page_size=2&page=2"))
    assert first + second == ["d", "c", "b", "a"]


def test_ordering_and_filters_work_together(api_client, priced):
    assert slugs(get(api_client, "min_price=200&ordering=-price")) == ["dear", "mid"]


# --- the four curated lists ------------------------------------------------------------------------------
CURATED = [
    ("new-arrivals", "is_new_arrival"),
    ("best-selling", "is_best_selling"),
    ("flash-sale", "is_flash_sale"),
    ("featured", "is_featured"),
]


@pytest.mark.parametrize(("path", "flag"), CURATED)
def test_curated_lists_show_only_flagged_active_products(api_client, path, flag):
    make_product("Flagged", **{flag: True})
    make_product("Not flagged")
    make_product("Flagged but hidden", is_active=False, **{flag: True})
    for url in (f"/api/v1/products/{path}/", f"/api/v1/products/{path}"):
        assert slugs(api_client.get(url)) == ["flagged"], url


@pytest.mark.parametrize(("path", "flag"), CURATED)
def test_curated_lists_paginate_and_ignore_filters(api_client, path, flag):
    for index in range(3):
        make_product(f"F{index}", **{flag: True})
    data = api_client.get(f"/api/v1/products/{path}/?page_size=2&brands=nobody").json()["data"]
    assert data["count"] == 3
    assert len(data["results"]) == 2
    assert set(data["results"][0]) == ITEM_KEYS


def test_best_selling_puts_the_most_ordered_first(api_client):
    make_product("Few", is_best_selling=True)
    many = make_product("Many", is_best_selling=True)
    Product.objects.filter(pk=many.pk).update(total_orders=50)
    assert slugs(api_client.get("/api/v1/products/best-selling/")) == ["many", "few"]


def test_other_curated_lists_are_newest_first(api_client):
    make_product("Old", is_featured=True)
    make_product("New", is_featured=True)
    assert slugs(api_client.get("/api/v1/products/featured/")) == ["new", "old"]


# --- is_favourite ----------------------------------------------------------------------------------------
@pytest.fixture
def favourite_provider(monkeypatch):
    """Stands in for the wishlist app (Step 7): the user has favourited the products in `ids`."""
    calls = []
    ids = set()

    def provider(user, product_ids):
        calls.append((user.pk, sorted(product_ids)))
        return ids & set(product_ids)

    monkeypatch.setattr(favourites, "_providers", [provider])
    provider.ids, provider.calls = ids, calls
    return provider


def test_is_favourite_is_personal_to_the_signed_in_user(api_client, favourite_provider):
    liked = make_product("Liked")
    make_product("Not liked")
    favourite_provider.ids.add(liked.pk)

    guest = {item["slug"]: item["is_favourite"] for item in get(api_client).json()["data"]["results"]}
    member = authed_client(verified_user())
    mine = {item["slug"]: item["is_favourite"] for item in get(member).json()["data"]["results"]}

    assert guest == {"liked": False, "not-liked": False}
    assert mine == {"liked": True, "not-liked": False}


def test_favourites_are_looked_up_once_per_page_for_that_page_only(favourite_provider):
    products = [make_product(f"P{index}") for index in range(5)]
    member = authed_client(verified_user())
    get(member, "page_size=2")
    assert len(favourite_provider.calls) == 1
    assert len(favourite_provider.calls[0][1]) == 2
    assert set(favourite_provider.calls[0][1]) <= {product.pk for product in products}


def test_a_guest_never_triggers_a_favourites_lookup(api_client, favourite_provider):
    make_product("P")
    get(api_client)
    assert favourite_provider.calls == []


def test_without_any_provider_nobody_has_favourites(monkeypatch):
    monkeypatch.setattr(favourites, "_providers", [])
    make_product("P")
    assert favourites.favourite_product_ids(verified_user(), [1, 2]) == frozenset()


def test_an_invalid_token_is_still_a_401_so_the_frontend_can_refresh(api_client):
    api_client.credentials(HTTP_AUTHORIZATION="Bearer not-a-token")
    assert get(api_client).status_code == 401


# --- query count -----------------------------------------------------------------------------------------
def count_queries(client, path):
    with CaptureQueriesContext(connection) as context:
        response = client.get(path)
    assert response.status_code == 200
    return len(context)


def build_catalog(size):
    brand = make_brand(f"Brand {size}")
    shared = make_tag(f"tag {size}")
    for index in range(size):
        product = make_product(f"Item {size}-{index}", brand=brand, discount_type="percentage", discount_value="10")
        product.tags.add(shared)
        make_media(product)
        make_variant(product, color=make_color(f"C{size}-{index}", "#112233"), stock_quantity=3)


def test_a_page_costs_the_same_number_of_queries_however_many_products_it_has(api_client):
    build_catalog(2)
    small = count_queries(api_client, LIST)
    build_catalog(9)
    large = count_queries(api_client, LIST)
    assert small == large == 2  # the page + the total


def test_signed_in_lists_stay_flat_too(favourite_provider):
    member = authed_client(verified_user())
    build_catalog(2)
    small = count_queries(member, LIST)
    build_catalog(9)
    assert count_queries(member, LIST) == small


def test_filtered_lists_stay_flat(api_client):
    build_catalog(2)
    query = "?brands=Brand 2&colors=C2-0&min_price=1&search=item&category=x&ordering=-discount_price"
    small = count_queries(api_client, LIST + query)
    build_catalog(9)
    assert count_queries(api_client, LIST + query) == small


def test_curated_lists_stay_flat(api_client):
    for index in range(2):
        sellable(make_product(f"A{index}", is_featured=True))
    small = count_queries(api_client, "/api/v1/products/featured/")
    for index in range(8):
        sellable(make_product(f"B{index}", is_featured=True))
    assert count_queries(api_client, "/api/v1/products/featured/") == small == 2
