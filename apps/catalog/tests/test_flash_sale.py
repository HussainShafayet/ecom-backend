"""The flash sale's window: with none set the marked products always show (the shop as it was); with one set they show only while
it is live, and the sale endpoints say how many seconds are left so the storefront can count down without the customer's clock."""
from datetime import datetime, timedelta, timezone as utc

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.catalog.flash_sale import flash_sale_state, is_live
from apps.catalog.models import FlashSale

from .helpers import make_category, make_product

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 10, 1, 12, 0, 0, tzinfo=utc.utc)
HOUR = timedelta(hours=1)
PRODUCTS = "/api/v1/products/flash-sale/"
CATEGORIES = "/api/v1/products/categories/flash-sale/"
WINDOW_KEYS = {"starts_at", "ends_at", "is_live", "starts_in_seconds", "ends_in_seconds"}


@pytest.fixture(autouse=True)
def the_time_is_fixed(monkeypatch):
    monkeypatch.setattr(timezone, "now", lambda: NOW)


def window(starts_at=None, ends_at=None):
    FlashSale.objects.update_or_create(pk=1, defaults={"starts_at": starts_at, "ends_at": ends_at})


def shown(api_client, url=PRODUCTS):
    response = api_client.get(url)
    assert response.status_code == 200, response.content
    return response.json()["data"]


# --- no window: the shop as it was -------------------------------------------------------------------------
def test_without_a_window_the_marked_products_always_show_and_there_is_no_countdown(api_client):
    make_product("Flash", is_flash_sale=True)
    data = shown(api_client)
    assert [item["slug"] for item in data["results"]] == ["flash"]
    assert data["flash_sale"] is None


def test_an_empty_row_is_the_same_as_no_row(api_client):
    FlashSale.load()
    make_product("Flash", is_flash_sale=True)
    assert shown(api_client)["flash_sale"] is None
    assert len(shown(api_client)["results"]) == 1
    assert flash_sale_state() is None and is_live(None) is True


def test_reading_the_window_never_writes_it(api_client):
    api_client.get(PRODUCTS)
    assert FlashSale.objects.count() == 0


# --- a live window ---------------------------------------------------------------------------------------
def test_inside_the_window_the_products_show_with_the_seconds_left(api_client):
    window(NOW - HOUR, NOW + timedelta(hours=2, seconds=30))
    make_product("Flash", is_flash_sale=True)
    data = shown(api_client)
    assert len(data["results"]) == 1
    assert set(data["flash_sale"]) == WINDOW_KEYS
    assert data["flash_sale"] | {"starts_at": None, "ends_at": None} == {
        "starts_at": None, "ends_at": None, "is_live": True, "starts_in_seconds": None, "ends_in_seconds": 7230,
    }
    assert data["flash_sale"]["ends_at"].startswith("2026-10-01T14:00:30")


def test_a_partial_second_counts_as_a_whole_one(api_client):
    window(None, NOW + timedelta(milliseconds=1))
    assert shown(api_client)["flash_sale"]["ends_in_seconds"] == 1


def test_an_end_alone_is_enough(api_client):
    window(None, NOW + HOUR)
    make_product("Flash", is_flash_sale=True)
    data = shown(api_client)
    assert len(data["results"]) == 1
    assert data["flash_sale"]["is_live"] is True
    assert data["flash_sale"]["ends_in_seconds"] == 3600


def test_a_start_alone_that_has_passed_keeps_the_sale_on_with_no_end(api_client):
    window(NOW - HOUR, None)
    make_product("Flash", is_flash_sale=True)
    data = shown(api_client)
    assert len(data["results"]) == 1
    assert data["flash_sale"]["is_live"] is True
    assert data["flash_sale"]["ends_in_seconds"] is None
    assert data["flash_sale"]["starts_in_seconds"] is None


# --- not live ----------------------------------------------------------------------------------------------
def test_before_the_start_the_list_is_empty_and_says_how_long_until_it_starts(api_client):
    window(NOW + timedelta(days=1), NOW + timedelta(days=2))
    make_product("Flash", is_flash_sale=True)
    data = shown(api_client)
    assert data["results"] == []
    assert data["count"] == 0
    assert data["flash_sale"]["is_live"] is False
    assert data["flash_sale"]["starts_in_seconds"] == 86400
    assert data["flash_sale"]["ends_in_seconds"] == 172800


def test_after_the_end_the_list_is_empty_and_the_seconds_left_are_zero(api_client):
    window(NOW - timedelta(days=2), NOW - HOUR)
    make_product("Flash", is_flash_sale=True)
    data = shown(api_client)
    assert data["results"] == []
    assert data["flash_sale"]["is_live"] is False
    assert data["flash_sale"]["ends_in_seconds"] == 0
    assert data["flash_sale"]["starts_in_seconds"] is None


def test_the_end_is_the_moment_it_stops_and_the_start_the_moment_it_begins(api_client):
    window(NOW, NOW + HOUR)  # begins exactly now
    assert shown(api_client)["flash_sale"]["is_live"] is True
    window(NOW - HOUR, NOW)  # ends exactly now
    assert shown(api_client)["flash_sale"]["is_live"] is False


def test_clearing_both_ends_shows_the_sale_again(api_client):
    window(NOW - timedelta(days=2), NOW - HOUR)
    make_product("Flash", is_flash_sale=True)
    assert shown(api_client)["results"] == []
    window(None, None)
    data = shown(api_client)
    assert len(data["results"]) == 1
    assert data["flash_sale"] is None


def test_a_page_past_the_end_still_carries_the_window(api_client):
    window(None, NOW + HOUR)
    make_product("Flash", is_flash_sale=True)
    data = shown(api_client, PRODUCTS + "?page=9")
    assert data["results"] == []
    assert data["flash_sale"]["ends_in_seconds"] == 3600


def test_pages_and_filters_work_as_before_inside_the_window(api_client):
    window(None, NOW + HOUR)
    for index in range(3):
        make_product(f"F{index}", is_flash_sale=True)
    data = shown(api_client, PRODUCTS + "?page_size=2")
    assert data["count"] == 3
    assert len(data["results"]) == 2
    assert data["next"]


# --- the categories ---------------------------------------------------------------------------------------
def test_the_marked_categories_follow_the_same_window(api_client):
    make_category("Sale", is_flash_sale=True)
    assert len(shown(api_client, CATEGORIES)["results"]) == 1

    window(None, NOW + HOUR)
    assert len(shown(api_client, CATEGORIES)["results"]) == 1

    window(NOW - timedelta(days=1), NOW - HOUR)
    assert shown(api_client, CATEGORIES)["results"] == []


def test_only_the_flash_sale_product_list_carries_the_window(api_client):
    window(None, NOW + HOUR)
    for path in ("new-arrivals", "best-selling", "featured"):
        assert "flash_sale" not in shown(api_client, f"/api/v1/products/{path}/")
    assert "flash_sale" not in shown(api_client, CATEGORIES)
    assert "flash_sale" not in shown(api_client, "/api/v1/products/")


def test_the_marked_products_still_show_everywhere_else_while_the_sale_is_over(api_client):
    window(NOW - timedelta(days=2), NOW - HOUR)
    make_product("Flash", is_flash_sale=True)
    data = shown(api_client, "/api/v1/products/")
    assert [item["slug"] for item in data["results"]] == ["flash"]


# --- the row ------------------------------------------------------------------------------------------------
def test_there_is_one_row_however_it_is_saved():
    FlashSale(pk=7).save()
    FlashSale().save()
    assert list(FlashSale.objects.values_list("pk", flat=True)) == [1]


def test_the_end_must_be_after_the_start():
    sale = FlashSale(starts_at=NOW, ends_at=NOW)
    with pytest.raises(ValidationError) as caught:
        sale.full_clean()
    assert "The end must be after the start." in str(caught.value)
    with pytest.raises(IntegrityError), transaction.atomic():
        FlashSale.objects.bulk_create([FlashSale(pk=1, starts_at=NOW, ends_at=NOW - HOUR)])


# --- the admin ----------------------------------------------------------------------------------------------
@pytest.fixture
def admin_client():
    user = get_user_model().objects.create_superuser("+8801700000000", password="s3cret-Pass!", name="Root")
    client = Client()
    client.force_login(user)
    return client


def test_the_menu_entry_opens_the_one_row_and_creates_it(admin_client):
    assert FlashSale.objects.count() == 0
    response = admin_client.get(reverse("admin:catalog_flashsale_changelist"))
    assert response.status_code == 302
    assert response.url == reverse("admin:catalog_flashsale_change", args=[1])
    assert FlashSale.objects.count() == 1


def test_the_owner_sets_the_window_and_the_page_says_what_it_does(admin_client):
    url = reverse("admin:catalog_flashsale_change", args=[FlashSale.load().pk])
    assert b"No window set" in admin_client.get(url).content

    response = admin_client.post(url, {
        "starts_at_0": "2026-10-01", "starts_at_1": "00:00:00", "ends_at_0": "2026-10-03", "ends_at_1": "23:59:59",
    })
    assert response.status_code == 302, response.content
    sale = FlashSale.objects.get()
    assert sale.starts_at is not None and sale.ends_at is not None
    assert b"Live" in admin_client.get(url).content


def test_the_admin_refuses_an_end_before_the_start(admin_client):
    url = reverse("admin:catalog_flashsale_change", args=[FlashSale.load().pk])
    response = admin_client.post(url, {
        "starts_at_0": "2026-10-03", "starts_at_1": "00:00:00", "ends_at_0": "2026-10-01", "ends_at_1": "00:00:00",
    })
    assert response.status_code == 200
    assert b"The end must be after the start." in response.content
    assert FlashSale.objects.get().ends_at is None


@pytest.mark.parametrize(
    ("starts_at", "ends_at", "says"),
    [
        (None, None, b"No window set"),
        (NOW - HOUR, NOW + HOUR, b"Live"),
        (NOW + HOUR, NOW + 2 * HOUR, b"Not started"),
        (NOW - 2 * HOUR, NOW - HOUR, b"Ended"),
    ],
)
def test_the_admin_page_says_where_the_sale_stands(admin_client, starts_at, ends_at, says):
    window(starts_at, ends_at)
    assert says in admin_client.get(reverse("admin:catalog_flashsale_change", args=[1])).content


def test_the_row_can_be_neither_added_nor_deleted_from_the_admin(admin_client):
    window()
    assert admin_client.get(reverse("admin:catalog_flashsale_add")).status_code == 403
    assert admin_client.post(reverse("admin:catalog_flashsale_delete", args=[1]), {"post": "yes"}).status_code == 403
    assert FlashSale.objects.count() == 1
