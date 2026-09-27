import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.siteconfig.models import SiteSettings

from .helpers import image_file, make_link, make_page, make_settings

pytestmark = pytest.mark.django_db

SITE_KEYS = {"name", "tagline", "logo", "announcement", "contact", "social_links", "footer_pages"}
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
    assert site(api_client)["announcement"] == {"text": "Sale!", "link": "/products/flash-sale"}


def test_an_announcement_without_a_link_has_a_null_link(api_client):
    make_settings(announcement_enabled=True, announcement_text="Closed on Friday")
    assert site(api_client)["announcement"] == {"text": "Closed on Friday", "link": None}


def test_a_switched_off_or_empty_announcement_is_not_sent(api_client):
    make_settings(announcement_enabled=False, announcement_text="Sale!")
    assert site(api_client)["announcement"] is None
    make_settings(announcement_enabled=True, announcement_text="   ")
    assert site(api_client)["announcement"] is None


# --- social links ------------------------------------------------------------------------------------------
def test_social_links_are_the_active_ones_in_the_admins_order(api_client):
    make_link("instagram", "https://instagram.com/shop", order=2)
    make_link("facebook", "https://facebook.com/shop", order=1)
    make_link("youtube", "https://youtube.com/shop", order=0, is_active=False)
    assert site(api_client)["social_links"] == [
        {"platform": "facebook", "url": "https://facebook.com/shop"},
        {"platform": "instagram", "url": "https://instagram.com/shop"},
    ]


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
    with CaptureQueriesContext(connection) as queries:
        assert api_client.get(URL).status_code == 200
    assert len(queries) <= 3
