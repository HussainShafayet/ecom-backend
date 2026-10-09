"""The "Only N left" notice: the product API says how many are left only when 1 to the shop's threshold are (5 unless the shop changed it), so
customers can hurry; with more, or none, `stock_left` is null and the real stock is never given away. Cards of products without options say it
themselves, a product with options says it on each colour and size."""
import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.catalog.models import StockNotice
from apps.catalog.stock_notice import left_if_low
from apps.catalog.tests.helpers import make_color, make_product, make_size, make_variant

pytestmark = pytest.mark.django_db

LIST = "/api/v1/products/"


def card(client, slug):
    response = client.get(LIST)
    assert response.status_code == 200, response.content
    return next(item for item in response.json()["data"]["results"] if item["slug"] == slug)


def detail(client, slug):
    response = client.get(f"/api/v1/products/detail/{slug}/")
    assert response.status_code == 200, response.content
    return response.json()["data"]


def plain(name, stock):
    product = make_product(name)
    make_variant(product, stock_quantity=stock)
    return product


class TestTheRule:
    @pytest.mark.parametrize(
        "stock, notice_at, expected",
        [(1, 5, 1), (3, 5, 3), (5, 5, 5), (6, 5, None), (100, 5, None), (0, 5, None), (3, 0, None), (1, 1, 1), (2, 1, None), (None, 5, None)],
    )
    def test_the_number_is_given_only_for_one_up_to_the_threshold(self, stock, notice_at, expected):
        assert left_if_low(stock, notice_at) == expected


class TestTheCard:
    def test_says_how_many_are_left_when_only_a_few_are(self, api_client):
        plain("Mug", 3)
        assert card(api_client, "mug")["stock_left"] == 3

    @pytest.mark.parametrize("stock, expected", [(1, 1), (5, 5), (6, None), (50, None), (0, None)])
    def test_the_default_threshold_is_five(self, api_client, stock, expected):
        plain("Mug", stock)
        assert card(api_client, "mug")["stock_left"] == expected

    def test_a_sold_out_product_says_nothing_about_how_many_are_left(self, api_client):
        plain("Mug", 0)
        item = card(api_client, "mug")
        assert item["stock_left"] is None
        assert item["availability_status"] is False

    def test_a_product_with_options_says_it_on_its_colours_and_sizes_not_on_the_card(self, api_client):
        product = make_product("Shirt")
        make_variant(product, color=make_color("Red", "#FF0000"), size=make_size("S", 1), stock_quantity=2)
        assert card(api_client, "shirt")["stock_left"] is None

    def test_follows_the_threshold_the_shop_set(self, api_client):
        plain("Mug", 3)
        StockNotice.objects.create(show_when_left=2)
        assert card(api_client, "mug")["stock_left"] is None
        StockNotice.objects.update(show_when_left=3)
        assert card(api_client, "mug")["stock_left"] == 3

    def test_can_be_switched_off(self, api_client):
        plain("Mug", 1)
        StockNotice.objects.create(show_when_left=0)
        assert card(api_client, "mug")["stock_left"] is None

    def test_reading_never_writes_the_setting(self, api_client):
        plain("Mug", 3)
        card(api_client, "mug")
        assert StockNotice.objects.count() == 0  # the default applies without a row

    def test_the_curated_lists_say_it_too(self, api_client):
        product = plain("Mug", 2)
        product.is_featured = True
        product.save()
        data = api_client.get("/api/v1/products/featured/").json()["data"]
        assert [item["stock_left"] for item in data["results"]] == [2]


class TestTheDetail:
    def test_a_product_without_options_says_it_like_its_card(self, api_client):
        plain("Mug", 4)
        assert detail(api_client, "mug")["stock_left"] == 4

    def test_each_size_says_how_many_of_it_are_left(self, api_client):
        product = make_product("Shirt")
        small, medium, large = make_size("S", 1), make_size("M", 2), make_size("L", 3)
        make_variant(product, size=small, stock_quantity=2)
        make_variant(product, size=medium, stock_quantity=40)
        make_variant(product, size=large, stock_quantity=0)

        data = detail(api_client, "shirt")

        assert data["stock_left"] is None  # the product itself has options
        assert [(size["name"], size["stock_left"]) for size in data["sizes"]] == [("S", 2), ("M", None), ("L", None)]

    def test_each_size_of_each_colour_does(self, api_client):
        product = make_product("Shirt")
        red, blue = make_color("Red", "#FF0000"), make_color("Blue", "#0000FF")
        small, medium = make_size("S", 1), make_size("M", 2)
        make_variant(product, color=red, size=small, stock_quantity=5)
        make_variant(product, color=red, size=medium, stock_quantity=6)
        make_variant(product, color=blue, size=small, stock_quantity=1)

        data = detail(api_client, "shirt")

        by_color = {color["name"]: [(size["name"], size["stock_left"]) for size in color["sizes"]] for color in data["colors"]}
        assert by_color == {"Red": [("S", 5), ("M", None)], "Blue": [("S", 1)]}

    def test_a_colour_sold_without_a_size_says_it_on_the_colour(self, api_client):
        product = make_product("Scarf")
        make_variant(product, color=make_color("Red", "#FF0000"), stock_quantity=3)
        make_variant(product, color=make_color("Blue", "#0000FF"), stock_quantity=30)

        data = detail(api_client, "scarf")

        assert {color["name"]: color["stock_left"] for color in data["colors"]} == {"Red": 3, "Blue": None}


class TestTheSetting:
    @pytest.fixture
    def admin_client(self):
        user = get_user_model().objects.create_superuser("+8801700000000", password="s3cret-Pass!", name="Root")
        client = Client()
        client.force_login(user)
        return client

    def test_the_menu_entry_opens_the_one_row_and_creates_it(self, admin_client):
        response = admin_client.get(reverse("admin:catalog_stocknotice_changelist"))
        assert response.status_code == 302
        assert StockNotice.objects.count() == 1
        assert response["Location"] == reverse("admin:catalog_stocknotice_change", args=[StockNotice.objects.get().pk])

    def test_the_owner_changes_it_and_the_shop_follows(self, admin_client, api_client):
        plain("Mug", 8)
        assert card(api_client, "mug")["stock_left"] is None
        url = reverse("admin:catalog_stocknotice_change", args=[StockNotice.load().pk])

        response = admin_client.post(url, {"show_when_left": "10", "_save": "Save"})

        assert response.status_code == 302
        assert StockNotice.current().show_when_left == 10
        assert card(api_client, "mug")["stock_left"] == 8

    @pytest.mark.parametrize("value", ["-1", "1001", "abc"])
    def test_a_silly_number_is_refused(self, admin_client, value):
        url = reverse("admin:catalog_stocknotice_change", args=[StockNotice.load().pk])
        response = admin_client.post(url, {"show_when_left": value, "_save": "Save"})
        assert response.status_code == 200  # the form again, with its problem
        assert StockNotice.current().show_when_left == 5

    def test_nobody_adds_a_second_row_or_deletes_the_only_one(self, admin_client):
        row = StockNotice.load()
        assert admin_client.get(reverse("admin:catalog_stocknotice_add")).status_code == 403
        assert admin_client.post(reverse("admin:catalog_stocknotice_delete", args=[row.pk]), {"post": "yes"}).status_code == 403
        assert StockNotice.objects.count() == 1

    def test_it_is_always_the_same_row(self):
        StockNotice(show_when_left=7).save()
        StockNotice(show_when_left=9).save()
        assert StockNotice.objects.count() == 1
        assert StockNotice.load().show_when_left == 9
