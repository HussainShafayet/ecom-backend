import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.catalog.tests.helpers import (
    image_file,
    make_brand,
    make_category,
    make_color,
    make_product,
    make_size,
    make_tag,
    make_variant,
)

pytestmark = pytest.mark.django_db

CATEGORY_KEYS = {"id", "name", "slug", "image", "has_discount", "discount_amount", "discount_type"}
CATEGORY_LISTS = [
    ("/api/v1/products/categories/", None),
    ("/api/v1/products/categories/flash-sale/", "is_flash_sale"),
    ("/api/v1/products/categories/new-arrival/", "is_new_arrival"),
    ("/api/v1/products/categories/best-selling/", "is_best_selling"),
    ("/api/v1/products/categories/feature/", "is_featured"),
]


def slugs(response):
    assert response.status_code == 200, response.content
    return [item["slug"] for item in response.json()["data"]["results"]]


# --- categories ----------------------------------------------------------------------------------------
def test_category_item_has_exactly_the_fields_the_frontend_reads(api_client):
    make_category("Shirts", discount_type="percentage", discount_amount="15", image=image_file())
    body = api_client.get("/api/v1/products/categories/").json()
    assert body["success"] is True
    item = body["data"]["results"][0]
    assert set(item) == CATEGORY_KEYS
    assert item["has_discount"] is True
    assert item["discount_amount"] == 15.0
    assert item["discount_type"] == "percentage"
    assert item["image"].startswith("http://testserver/media/categories/")


def test_category_without_discount_or_image(api_client):
    make_category("Plain")
    item = api_client.get("/api/v1/products/categories/").json()["data"]["results"][0]
    assert item["has_discount"] is False
    assert item["discount_type"] is None
    assert item["image"] is None


@pytest.mark.parametrize(("path", "flag"), CATEGORY_LISTS)
def test_category_lists_show_active_categories_a_to_z(api_client, path, flag):
    flagged = {flag: True} if flag else {}
    make_category("Zebra", **flagged)
    make_category("Apple", **flagged)
    make_category("Hidden", is_active=False, **flagged)
    if flag:
        make_category("Not flagged")
    assert slugs(api_client.get(path)) == ["apple", "zebra"]


@pytest.mark.parametrize(("path", "flag"), CATEGORY_LISTS)
def test_category_lists_paginate_and_answer_both_slash_variants(api_client, path, flag):
    for name in ("A", "B", "C"):
        make_category(name, **({flag: True} if flag else {}))
    data = api_client.get(f"{path}?page=1&page_size=2").json()["data"]
    assert data["count"] == 3 and len(data["results"]) == 2
    assert api_client.get(path.rstrip("/")).status_code == 200
    assert api_client.get(f"{path}?page=9").json()["data"]["results"] == []


# --- search suggestions ------------------------------------------------------------------------------------
SUGGEST = "/api/v1/products/search-suggestions/"


def suggestions(client, q):
    response = client.get(SUGGEST, {"q": q})
    assert response.status_code == 200, response.content
    return response.json()["data"]


def test_suggestions_are_plain_product_names_starting_matches_first(api_client):
    make_product("Blue Shirt")
    make_product("Shirt Red")
    make_product("Shoes")
    assert suggestions(api_client, "shirt") == ["Shirt Red", "Blue Shirt"]
    assert suggestions(api_client, "SH") == ["Shirt Red", "Shoes", "Blue Shirt"]


def test_suggestions_are_capped_at_ten_and_unique(api_client):
    for index in range(14):
        make_product(f"Shirt {index:02d}")
    make_product("Twin")
    make_product("Twin")
    assert len(suggestions(api_client, "shirt")) == 10
    assert suggestions(api_client, "twin") == ["Twin"]


def test_suggestions_skip_hidden_products_and_blank_queries(api_client):
    make_product("Shirt")
    make_product("Shirt hidden", is_active=False)
    assert suggestions(api_client, "shirt") == ["Shirt"]
    assert suggestions(api_client, "") == []
    assert suggestions(api_client, "   ") == []
    assert api_client.get(SUGGEST).json()["data"] == []  # no q at all


def test_suggestions_take_percent_literally_and_nothing_matches_nothing(api_client):
    make_product("50% Cotton")
    make_product("Shirt")
    assert suggestions(api_client, "%") == ["50% Cotton"]
    assert suggestions(api_client, "zzz") == []


# --- shop content --------------------------------------------------------------------------------------
SHOP = "/api/v1/content/shop/"


def shop(client):
    response = client.get(SHOP)
    assert response.status_code == 200, response.content
    return response.json()["data"]


def test_an_empty_shop_has_empty_filters_and_a_zero_price_range(api_client):
    assert shop(api_client) == {
        "categories": [],
        "brands": [],
        "tags": [],
        "colors": [],
        "sizes": [],
        "price_range": {"min_range": 0, "max_range": 0},
        "discounts": [],
    }


def test_shop_content_has_the_shape_the_sidebar_reads(api_client):
    brand, tag = make_brand("Acme"), make_tag("eco")
    red, small = make_color("Red", "#FF0000"), make_size("S", 1)
    product = make_product("Shirt", base_price="1000.00", discount_type="percentage", discount_value="10", brand=brand)
    product.tags.add(tag)
    make_variant(product, color=red, size=small, stock_quantity=1)
    make_category("Shirts")

    data = shop(api_client)

    assert set(data) == {"categories", "brands", "tags", "colors", "sizes", "price_range", "discounts"}
    assert data["categories"] == [{"name": "Shirts", "slug": "shirts", "children": []}]
    assert data["brands"] == ["Acme"]
    assert data["tags"] == ["eco"]
    assert data["colors"] == [{"name": "Red", "hex_code": "#FF0000"}]
    assert data["sizes"] == ["S"]
    assert data["price_range"] == {"min_range": 900.0, "max_range": 900.0}
    assert data["discounts"] == [{"discount_type": "percentage", "value": 10.0}]


def test_categories_are_a_nested_tree_of_active_nodes(api_client):
    clothing = make_category("Clothing")
    shirts = make_category("Shirts", parent=clothing)
    make_category("Polo", parent=shirts)
    make_category("Hoodies", parent=clothing)
    make_category("Hidden child", parent=clothing, is_active=False)
    hidden_root = make_category("Hidden root", is_active=False)
    make_category("Under hidden root", parent=hidden_root)
    make_category("Accessories")

    tree = shop(api_client)["categories"]

    assert [node["slug"] for node in tree] == ["accessories", "clothing"]
    clothing_node = tree[1]
    assert [child["slug"] for child in clothing_node["children"]] == ["hoodies", "shirts"]
    shirts_node = clothing_node["children"][1]
    assert shirts_node["children"] == [{"name": "Polo", "slug": "polo", "children": []}]


def test_only_values_a_visible_product_has_are_listed(api_client):
    used_brand, unused_brand = make_brand("Used"), make_brand("Unused")
    make_brand("Only hidden")
    live = make_product("Live", brand=used_brand)
    hidden = make_product("Hidden", is_active=False, brand=unused_brand)
    live.tags.add(make_tag("used"))
    hidden.tags.add(make_tag("unused"))
    red, blue, green = make_color("Red", "#FF0000"), make_color("Blue", "#0000FF"), make_color("Green", "#00FF00")
    small, medium, large = make_size("S", 1), make_size("M", 2), make_size("L", 3)
    make_variant(live, color=red, size=small, stock_quantity=1)
    make_variant(live, color=blue, size=medium, stock_quantity=1, is_active=False)  # variant off
    make_variant(hidden, color=green, size=large, stock_quantity=1)  # product off

    data = shop(api_client)

    assert data["brands"] == ["Used"]
    assert data["tags"] == ["used"]
    assert [color["name"] for color in data["colors"]] == ["Red"]
    assert data["sizes"] == ["S"]


def test_sizes_come_in_size_order_and_names_a_to_z(api_client):
    product = make_product("P")
    for name, order in (("L", 3), ("S", 1), ("M", 2)):
        make_variant(product, size=make_size(name, order), stock_quantity=1)
    for name in ("Zed", "Acme"):
        make_product(f"Of {name}", brand=make_brand(name))
    data = shop(api_client)
    assert data["sizes"] == ["S", "M", "L"]
    assert data["brands"] == ["Acme", "Zed"]


def test_price_range_is_what_customers_pay_and_ignores_hidden_products(api_client):
    make_product("Cheap", base_price="100.00")
    make_product("Half price", base_price="1000.00", discount_type="percentage", discount_value="50")
    make_product("Dear", base_price="900.00")
    make_product("Hidden and cheaper", base_price="1.00", is_active=False)
    make_product("Hidden and dearer", base_price="99999.00", is_active=False)
    assert shop(api_client)["price_range"] == {"min_range": 100.0, "max_range": 900.0}


def test_discounts_are_distinct_pairs_of_visible_products(api_client):
    make_product("A", base_price="500", discount_type="percentage", discount_value="10")
    make_product("B", base_price="500", discount_type="percentage", discount_value="10")
    make_product("C", base_price="500", discount_type="fixed", discount_value="50")
    make_product("D", base_price="500", discount_type="percentage", discount_value="5")
    make_product("None")
    make_product("Hidden", base_price="500", discount_type="fixed", discount_value="99", is_active=False)
    assert shop(api_client)["discounts"] == [
        {"discount_type": "fixed", "value": 50.0},
        {"discount_type": "percentage", "value": 5.0},
        {"discount_type": "percentage", "value": 10.0},
    ]


def test_every_discount_listed_works_as_a_filter(api_client):
    make_product("Ten", base_price="500", discount_type="percentage", discount_value="10")
    make_product("Fifty", base_price="500", discount_type="fixed", discount_value="50")
    for entry in shop(api_client)["discounts"]:
        response = api_client.get("/api/v1/products/", {"discount_type": entry["discount_type"], "discount_value": entry["value"]})
        assert response.json()["data"]["count"] == 1, entry


def test_shop_content_is_public_and_answers_both_slash_variants(api_client):
    assert api_client.get("/api/v1/content/shop").status_code == 200
    assert api_client.get("/api/v1/content/shop/").status_code == 200


def test_shop_content_query_count_does_not_grow_with_the_catalog(api_client):
    def build(prefix, count):
        for index in range(count):
            product = make_product(f"{prefix}{index}", brand=make_brand(f"B{prefix}{index}"))
            product.tags.add(make_tag(f"t{prefix}{index}"))
            make_variant(product, color=make_color(f"C{prefix}{index}", "#000000"), size=make_size(f"Z{prefix}{index}"), stock_quantity=1)
            make_category(f"Cat {prefix}{index}")

    def queries():
        with CaptureQueriesContext(connection) as context:
            assert api_client.get(SHOP).status_code == 200
        return len(context)

    build("a", 2)
    small = queries()
    build("b", 10)
    assert queries() == small
