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
from apps.catalog.tests.test_api_products import ITEM_KEYS

pytestmark = pytest.mark.django_db

DETAIL_ONLY_KEYS = {
    "brand", "categories", "category", "tags", "thumbnail", "media_files", "minimum_order_quantity",
    "short_description", "long_description", "model", "weight", "dimension", "material", "features",
    "warranty_information", "shipping_information", "return_policy", "qrcode_image_url",
}  # fmt: skip


def url(slug):
    return f"/api/v1/products/detail/{slug}/"


def detail(client, slug):
    response = client.get(url(slug))
    assert response.status_code == 200, response.content
    return response.json()["data"]


@pytest.fixture
def red():
    return make_color("Red", "#FF0000")


@pytest.fixture
def blue():
    return make_color("Blue", "#0000FF")


@pytest.fixture
def sizes():
    return make_size("S", 1), make_size("M", 2), make_size("L", 3)


# --- shape ---------------------------------------------------------------------------------------------
def test_plain_product_has_every_field_but_neither_colors_nor_sizes(api_client):
    product = make_product("Mug", base_price="300.00", minimum_order_quantity=2, brand=make_brand("Acme"))
    make_variant(product, stock_quantity=4)
    make_media(product)

    data = detail(api_client, "mug")

    assert set(data) == ITEM_KEYS | DETAIL_ONLY_KEYS
    assert "colors" not in data and "sizes" not in data  # the frontend tests `!product.colors`
    assert data["minimum_order_quantity"] == 2
    assert data["brand"] == {"name": "Acme"}
    assert data["variant_id"] == product.variants.get().pk
    assert data["availability_status"] is True


def test_absent_optional_parts_are_null_or_empty_not_missing(api_client):
    make_product("Bare")
    data = detail(api_client, "bare")
    assert data["brand"] is None
    assert data["category"] is None
    assert data["categories"] == [] and data["tags"] == [] and data["media_files"] == []
    assert data["thumbnail"] is None
    assert data["dimension"] is None
    assert data["image"] is None


def test_urls_are_absolute(api_client):
    product = make_product("Mug")
    make_media(product)
    data = detail(api_client, "mug")
    for value in (data["image"], data["thumbnail"], data["qrcode_image_url"], data["media_files"][0]["file_url"]):
        assert value.startswith("http://testserver/media/"), value
    assert data["media_files"][0]["thumbnail_url"].startswith("http://testserver/media/")


def test_categories_primary_category_tags_and_dimension(api_client):
    clothing = make_category("Clothing")
    shirts = make_category("Shirts", parent=clothing)
    hidden = make_category("Hidden", is_active=False)
    product = make_product(
        "Shirt", dimension_width="10.5", dimension_height="20", dimension_depth="3", primary_category=shirts
    )
    product.categories.add(clothing, shirts, hidden)
    product.tags.add(make_tag("sale"), make_tag("eco"))

    data = detail(api_client, "shirt")

    assert data["categories"] == [{"name": "Clothing", "slug": "clothing"}, {"name": "Shirts", "slug": "shirts"}]
    assert data["category"] == "shirts"
    assert data["tags"] == [{"name": "eco"}, {"name": "sale"}]
    assert data["dimension"] == {"width": 10.5, "height": 20.0, "depth": 3.0}


def test_a_hidden_primary_category_falls_back_to_a_visible_one(api_client):
    hidden = make_category("Hidden", is_active=False)
    visible = make_category("Visible")
    product = make_product("P", primary_category=hidden)
    product.categories.add(hidden, visible)
    assert detail(api_client, "p")["category"] == "visible"


def test_long_description_is_the_sanitized_html(api_client):
    make_product("P", long_description='<p onclick="x()">Hello</p><script>alert(1)</script>')
    body = detail(api_client, "p")["long_description"]
    assert "<script" not in body and "onclick" not in body
    assert "Hello" in body


# --- colours and sizes -----------------------------------------------------------------------------------
def test_colors_hold_their_sizes_in_size_order(api_client, red, blue, sizes):
    small, medium, large = sizes
    product = make_product("Shirt", base_price="1000.00", discount_type="percentage", discount_value="10")
    make_variant(product, color=red, size=large, stock_quantity=2)
    make_variant(product, color=red, size=small, stock_quantity=0)
    make_variant(product, color=red, size=medium, stock_quantity=5, base_price="1200.00")
    make_variant(product, color=blue, size=small, stock_quantity=7)

    data = detail(api_client, "shirt")

    assert "sizes" not in data
    assert [color["name"] for color in data["colors"]] == ["Red", "Blue"]  # the default variant's colour first
    first = data["colors"][0]
    assert first["hex_code"] == "#FF0000"
    assert [size["name"] for size in first["sizes"]] == ["S", "M", "L"]
    small_entry, medium_entry, large_entry = first["sizes"]
    assert set(small_entry) == {"name", "variant_id", "base_price", "discount_price", "availability_status"}
    assert small_entry["availability_status"] is False  # out of stock
    assert large_entry["availability_status"] is True
    assert (medium_entry["base_price"], medium_entry["discount_price"]) == (1200.0, 1080.0)  # own price, product rule
    assert (large_entry["base_price"], large_entry["discount_price"]) == (1000.0, 900.0)
    assert "variant_id" not in first  # only a colour sold without a size carries one
    assert data["has_variants"] is True


def test_the_variant_ids_are_the_ones_the_cart_will_take(api_client, red, sizes):
    product = make_product("Shirt")
    variant = make_variant(product, color=red, size=sizes[0], stock_quantity=1)
    entry = detail(api_client, "shirt")["colors"][0]["sizes"][0]
    assert entry["variant_id"] == variant.pk


def test_a_colour_sold_without_sizes_carries_its_own_variant_and_price(api_client, red, blue):
    product = make_product("Watch", base_price="500.00")
    make_variant(product, color=red, stock_quantity=3, base_price="550.00", discount_price="500.00")
    variant = make_variant(product, color=blue, stock_quantity=0)

    colors = {color["name"]: color for color in detail(api_client, "watch")["colors"]}

    assert colors["Red"]["sizes"] == []
    assert (colors["Red"]["base_price"], colors["Red"]["discount_price"]) == (550.0, 500.0)
    assert colors["Red"]["availability_status"] is True
    assert colors["Blue"]["variant_id"] == variant.pk
    assert colors["Blue"]["availability_status"] is False


def test_sizes_only_product_has_sizes_and_no_colors(api_client, sizes):
    small, medium, _ = sizes
    product = make_product("Cap")
    make_variant(product, size=medium, stock_quantity=1)
    make_variant(product, size=small, stock_quantity=1)

    data = detail(api_client, "cap")

    assert "colors" not in data
    assert [size["name"] for size in data["sizes"]] == ["S", "M"]
    assert data["has_variants"] is True


def test_inactive_variants_are_not_offered(api_client, red, sizes):
    product = make_product("Shirt")
    make_variant(product, color=red, size=sizes[0], stock_quantity=1)
    make_variant(product, color=red, size=sizes[1], stock_quantity=1, is_active=False)
    assert [size["name"] for size in detail(api_client, "shirt")["colors"][0]["sizes"]] == ["S"]


def test_default_variant_drives_the_top_level_price_and_variant_id(api_client, red, blue):
    product = make_product("Watch", base_price="500.00")
    default = make_variant(product, color=red, base_price="700.00", stock_quantity=1)
    make_variant(product, color=blue, stock_quantity=1)
    data = detail(api_client, "watch")
    assert data["variant_id"] == default.pk
    assert data["base_price"] == 700.0


# --- media ---------------------------------------------------------------------------------------------
def test_top_level_media_is_the_shared_gallery_and_colours_get_their_own(api_client, red, blue):
    product = make_product("Shirt")
    make_variant(product, color=red, stock_quantity=1)
    make_variant(product, color=blue, stock_quantity=1)
    shared = make_media(product, order=0)
    red_photo = make_media(product, color=red, order=0)
    make_media(product, color=red, order=1, video=True)

    data = detail(api_client, "shirt")

    assert [m["file_type"] for m in data["media_files"]] == ["image"]
    assert data["media_files"][0]["file_url"].endswith(shared.file.name)
    colors = {color["name"]: color for color in data["colors"]}
    assert [m["file_type"] for m in colors["Red"]["media_files"]] == ["image", "video"]
    assert colors["Red"]["media_files"][0]["file_url"].endswith(red_photo.file.name)
    # Blue has no photos of its own, so the frontend (which shows only the colour's gallery) gets the shared ones.
    assert colors["Blue"]["media_files"] == data["media_files"]


def test_a_video_has_a_thumbnail_only_when_a_poster_exists(api_client):
    product = make_product("Clip")
    make_media(product, video=True)
    entry = detail(api_client, "clip")["media_files"][0]
    assert entry["file_type"] == "video"
    assert entry["thumbnail_url"] is None


def test_without_colours_every_media_file_is_in_the_gallery_in_admin_order(api_client, red):
    product = make_product("Mug")
    late = make_media(product, order=5)
    stray = make_media(product, color=red, order=2)  # tied to a colour the product does not sell
    early = make_media(product, order=1)
    urls = [m["file_url"] for m in detail(api_client, "mug")["media_files"]]
    assert [u.rsplit("/media/", 1)[1] for u in urls] == [early.file.name, stray.file.name, late.file.name]


def test_thumbnail_is_the_main_images_thumbnail(api_client, red):
    product = make_product("Mug")
    make_media(product, color=red, order=0)
    shared = make_media(product, order=3)
    assert detail(api_client, "mug")["thumbnail"].endswith(shared.thumbnail.name)


# --- views counter --------------------------------------------------------------------------------------
def test_opening_a_product_counts_a_view(api_client):
    product = make_product("Mug")
    Product.objects.filter(pk=product.pk).update(total_views=10)
    before = Product.objects.get(pk=product.pk).updated_at

    assert detail(api_client, "mug")["total_views"] == 11
    assert detail(api_client, "mug")["total_views"] == 12

    product.refresh_from_db()
    assert product.total_views == 12
    assert product.updated_at == before  # a view is not an edit


def test_the_list_does_not_count_views(api_client):
    product = make_product("Mug")
    api_client.get("/api/v1/products/")
    product.refresh_from_db()
    assert product.total_views == 0


# --- not found / access ---------------------------------------------------------------------------------
def test_unknown_and_inactive_products_are_404(api_client):
    make_product("Hidden", is_active=False)
    for slug in ("hidden", "nope"):
        response = api_client.get(url(slug))
        assert response.status_code == 404
        assert response.json()["success"] is False


def test_a_hidden_product_does_not_get_its_view_counted(api_client):
    hidden = make_product("Hidden", is_active=False)
    api_client.get(url("hidden"))
    hidden.refresh_from_db()
    assert hidden.total_views == 0


def test_both_slash_variants_and_no_login_needed(api_client):
    make_product("Mug")
    for path in ("/api/v1/products/detail/mug/", "/api/v1/products/detail/mug"):
        assert api_client.get(path).status_code == 200, path


def test_is_favourite_on_the_detail_page(api_client, monkeypatch):
    product = make_product("Mug")
    monkeypatch.setattr(favourites, "_providers", [lambda user, ids: {product.pk} & set(ids)])
    assert detail(api_client, "mug")["is_favourite"] is False
    assert detail(authed_client(verified_user()), "mug")["is_favourite"] is True


# --- query count -----------------------------------------------------------------------------------------
def build_variants(product, count):
    for index in range(count):
        color = make_color(f"C{product.pk}-{index}", "#123456")
        for size_index in range(2):
            make_variant(product, color=color, size=make_size(f"S{product.pk}-{index}-{size_index}", size_index), stock_quantity=1)
        make_media(product, color=color)


def count_queries(client, path):
    with CaptureQueriesContext(connection) as context:
        assert client.get(path).status_code == 200
    return len(context)


def test_detail_costs_the_same_queries_for_a_small_and_a_large_product(api_client):
    small = make_product("Small")
    build_variants(small, 1)
    large = make_product("Large")
    for tag in ("a", "b", "c", "d"):
        large.tags.add(make_tag(tag))
    build_variants(large, 6)
    for index in range(4):
        large.categories.add(make_category(f"Cat {index}"))

    assert count_queries(api_client, url("small")) == count_queries(api_client, url("large"))


def test_detail_query_budget(api_client):
    product = make_product("P")
    build_variants(product, 3)
    # product, variants, categories, media, tags, the view counter's UPDATE
    assert count_queries(api_client, url("p")) <= 6
