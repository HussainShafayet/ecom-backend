from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.siteconfig import services
from apps.siteconfig.models import SiteSettings

from .helpers import image_file, make_badge, make_link, make_page, make_settings

pytestmark = pytest.mark.django_db

SITE_KEYS = {"name", "tagline", "logo", "announcement", "contact", "social_links", "trust_badges", "footer_pages"}
CONTACT_KEYS = {"email", "phone", "address", "opening_hours", "map_url"}
URL = "/api/v1/site/"


def site(client):
    response = client.get(URL)
    assert response.status_code == 200, response.content
    return response.json()["data"]["site"]


def test_the_envelope_and_the_shape(api_client):
    body = api_client.get(URL).json()
    assert body["success"] is True
    assert set(body["data"]) == {"site"}
    assert set(body["data"]["site"]) == SITE_KEYS
    assert set(body["data"]["site"]["contact"]) == CONTACT_KEYS


@pytest.mark.parametrize("path", ["/api/v1/site", "/api/v1/site/"])
def test_both_spellings_answer(api_client, path):
    assert api_client.get(path).status_code == 200


def test_a_shop_that_saved_nothing_gets_the_defaults_and_nothing_is_written(api_client):
    data = site(api_client)
    assert data["name"] == "My Shop"
    assert data["logo"] is None and data["announcement"] is None and data["social_links"] == []
    assert data["trust_badges"] == []
    assert data["footer_pages"] == {"company": [], "service": [], "legal": []}
    assert SiteSettings.objects.count() == 0


def test_the_name_tagline_and_contact_details(api_client):
    make_settings(
        site_name="GoCart",
        tagline="Delivered",
        contact_email="hi@example.com",
        contact_phone="+880 1700",
        contact_address="Dhaka",
        opening_hours="Sat - Thu",
        map_embed_url="https://www.openstreetmap.org/export/embed.html?bbox=1%2C2%2C3%2C4",
    )
    data = site(api_client)
    assert (data["name"], data["tagline"]) == ("GoCart", "Delivered")
    assert data["contact"] == {
        "email": "hi@example.com",
        "phone": "+880 1700",
        "address": "Dhaka",
        "opening_hours": "Sat - Thu",
        "map_url": "https://www.openstreetmap.org/export/embed.html?bbox=1%2C2%2C3%2C4",
    }


def test_the_logo_is_an_absolute_address(api_client):
    make_settings(logo=image_file())
    logo = site(api_client)["logo"]
    assert logo.startswith("http://testserver/media/site/") and logo.endswith(".png")


# --- the announcement bar ---------------------------------------------------------------------------------
def test_an_enabled_announcement_is_shown_with_its_link(api_client):
    make_settings(announcement_enabled=True, announcement_text="Sale!", announcement_link="/products/flash-sale")
    assert site(api_client)["announcement"] == {"text": "Sale!", "link": "/products/flash-sale", "ends_in_seconds": None}


def test_an_announcement_without_a_link_has_a_null_link(api_client):
    make_settings(announcement_enabled=True, announcement_text="Closed on Friday")
    assert site(api_client)["announcement"] == {"text": "Closed on Friday", "link": None, "ends_in_seconds": None}


def test_a_switched_off_or_empty_announcement_is_not_sent(api_client):
    make_settings(announcement_enabled=False, announcement_text="Sale!")
    assert site(api_client)["announcement"] is None
    make_settings(announcement_enabled=True, announcement_text="   ")
    assert site(api_client)["announcement"] is None


def test_an_announcement_with_an_end_in_the_future_says_how_long_is_left(api_client):
    make_settings(announcement_enabled=True, announcement_text="Sale!", announcement_ends_at=timezone.now() + timedelta(hours=2))
    bar = site(api_client)["announcement"]
    assert bar["text"] == "Sale!"
    assert 7190 <= bar["ends_in_seconds"] <= 7200  # measured by the server, a little under two hours by the time it answers


def test_an_announcement_whose_end_has_passed_is_not_sent_even_when_switched_on(api_client):
    make_settings(announcement_enabled=True, announcement_text="Sale!", announcement_ends_at=timezone.now() - timedelta(seconds=1))
    assert site(api_client)["announcement"] is None


def test_the_bar_comes_back_when_the_end_is_moved_and_goes_for_good_when_it_is_cleared_or_switched_off(api_client):
    make_settings(announcement_enabled=True, announcement_text="Sale!", announcement_ends_at=timezone.now() - timedelta(days=1))
    assert site(api_client)["announcement"] is None
    make_settings(announcement_ends_at=timezone.now() + timedelta(days=1))  # the admin extends the sale
    assert site(api_client)["announcement"]["ends_in_seconds"] > 0
    make_settings(announcement_ends_at=None)  # no end after all
    assert site(api_client)["announcement"]["ends_in_seconds"] is None
    make_settings(announcement_ends_at=timezone.now() + timedelta(days=1), announcement_enabled=False)  # an end never switches it on
    assert site(api_client)["announcement"] is None


def test_the_end_moment_itself_is_already_over_and_the_seconds_round_up():
    ends_at = timezone.now() + timedelta(days=1)
    site_row = SiteSettings(announcement_enabled=True, announcement_text="Sale!", announcement_ends_at=ends_at)
    assert services.announcement(site_row, ends_at) is None
    assert services.announcement(site_row, ends_at + timedelta(seconds=1)) is None
    assert services.announcement(site_row, ends_at - timedelta(seconds=1))["ends_in_seconds"] == 1
    assert services.announcement(site_row, ends_at - timedelta(milliseconds=200))["ends_in_seconds"] == 1  # never 0 while a moment is left
    assert services.announcement(site_row, ends_at - timedelta(seconds=90, milliseconds=500))["ends_in_seconds"] == 91
    make_settings(announcement_enabled=True, announcement_text="Sale!", announcement_ends_at=ends_at)  # and the same through the saved row
    assert services.site_payload(now=ends_at)["announcement"] is None
    assert services.site_payload(now=ends_at - timedelta(minutes=1))["announcement"]["ends_in_seconds"] == 60


# --- social links ------------------------------------------------------------------------------------------
def test_social_links_are_the_active_ones_in_the_admins_order(api_client):
    make_link("instagram", "https://instagram.com/shop", order=2)
    make_link("facebook", "https://facebook.com/shop", order=1)
    make_link("youtube", "https://youtube.com/shop", order=0, is_active=False)
    assert site(api_client)["social_links"] == [
        {"platform": "facebook", "url": "https://facebook.com/shop"},
        {"platform": "instagram", "url": "https://instagram.com/shop"},
    ]


# --- trust badges -------------------------------------------------------------------------------------------
def test_trust_badges_are_the_active_ones_in_the_admins_order(api_client):
    make_badge("returns", "Easy returns", order=1)
    make_badge("delivery", "Free delivery", order=0)
    make_badge("support", "Hidden", order=2, is_active=False)
    assert site(api_client)["trust_badges"] == [
        {"icon": "delivery", "title": "Free delivery", "subtitle": ""},
        {"icon": "returns", "title": "Easy returns", "subtitle": ""},
    ]


def test_a_trust_badge_can_have_a_subtitle(api_client):
    make_badge("secure_payment", "Secure payment", subtitle="256-bit SSL")
    assert site(api_client)["trust_badges"] == [{"icon": "secure_payment", "title": "Secure payment", "subtitle": "256-bit SSL"}]


# --- footer pages ------------------------------------------------------------------------------------------
def test_footer_pages_are_grouped_published_and_ordered(api_client):
    make_page("about-us", "About Us", footer_group="company", order=1)
    make_page("careers", "Careers", footer_group="company", order=0)
    make_page("shipping", "Shipping", footer_group="service")
    make_page("privacy-policy", "Privacy Policy", footer_group="legal")
    make_page("draft", "Draft", footer_group="legal", is_published=False)
    make_page("hidden", "Not in the footer")
    assert site(api_client)["footer_pages"] == {
        "company": [{"slug": "careers", "title": "Careers"}, {"slug": "about-us", "title": "About Us"}],
        "service": [{"slug": "shipping", "title": "Shipping"}],
        "legal": [{"slug": "privacy-policy", "title": "Privacy Policy"}],
    }


# --- public, cheap ------------------------------------------------------------------------------------------
def test_a_stale_or_garbage_token_is_not_a_401(api_client):
    api_client.credentials(HTTP_AUTHORIZATION="Bearer not-a-token")
    assert api_client.get(URL).status_code == 200


def test_the_answer_costs_a_fixed_number_of_queries(api_client):
    make_settings(site_name="GoCart")
    for index in range(5):
        make_link(["facebook", "instagram", "x", "youtube", "tiktok"][index], f"https://example.com/{index}")
        make_page(f"p{index}", f"P{index}", footer_group="company")
        make_badge(["delivery", "returns", "secure_payment", "cash_on_delivery", "support"][index], f"Badge {index}")
    with CaptureQueriesContext(connection) as queries:
        assert api_client.get(URL).status_code == 200
    assert len(queries) <= 4
