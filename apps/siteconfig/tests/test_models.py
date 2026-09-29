import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.core.files.storage import default_storage

from apps.siteconfig.models import ContactMessage, NewsletterSubscriber, SiteSettings, SocialLink, StaticPage, TrustBadge
from apps.siteconfig.validators import validate_link, validate_map_embed

from .helpers import image_file, make_badge, make_link, make_page, make_settings

pytestmark = pytest.mark.django_db


# --- the one settings row -------------------------------------------------------------------------------
def test_load_creates_the_row_once_with_the_defaults():
    first = SiteSettings.load()
    assert (first.pk, first.site_name) == (1, "My Shop")
    assert SiteSettings.load().pk == 1
    assert SiteSettings.objects.count() == 1


def test_current_never_writes():
    site = SiteSettings.current()
    assert site.pk is None and site.site_name == "My Shop"
    assert SiteSettings.objects.count() == 0


def test_saving_another_instance_updates_the_same_row():
    make_settings(site_name="First")
    SiteSettings(site_name="Second").save()
    assert SiteSettings.objects.count() == 1
    assert SiteSettings.load().site_name == "Second"


def test_the_database_refuses_a_second_row():
    with pytest.raises(IntegrityError), transaction.atomic():
        SiteSettings.objects.bulk_create([SiteSettings(id=2)])


def test_replacing_the_logo_removes_the_old_file(django_capture_on_commit_callbacks):
    site = make_settings(logo=image_file("a.png"))
    old = site.logo.name
    assert default_storage.exists(old)
    with django_capture_on_commit_callbacks(execute=True):
        site.logo = image_file("b.png")
        site.save()
    assert not default_storage.exists(old)


# --- links and maps ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("value", ["/products/flash-sale", "/", "/pages/about-us", "https://example.com/sale", "http://example.com"])
def test_a_link_can_be_a_shop_page_or_a_website(value):
    validate_link(value)


@pytest.mark.parametrize(
    "value",
    ["javascript:alert(1)", "//evil.example", "/ path", "/a\\b", "products", "data:text/html,x", "ftp://example.com", "mailto:a@b.co"],
)
def test_a_link_is_never_a_script_or_a_protocol_relative_address(value):
    with pytest.raises(ValidationError):
        validate_link(value)


@pytest.mark.parametrize(
    "value",
    [
        "https://www.google.com/maps/embed?pb=!1m18",
        "https://maps.google.com/maps/embed?x=1",
        "https://www.openstreetmap.org/export/embed.html?bbox=1%2C2%2C3%2C4",
    ],
)
def test_a_map_can_be_a_google_or_openstreetmap_embed(value):
    validate_map_embed(value)


@pytest.mark.parametrize(
    "value",
    [
        "http://www.google.com/maps/embed?pb=1",  # not https
        "https://www.google.com/search?q=maps",  # not an embed page
        "https://evil.example/maps/embed",  # not a map site
        "https://www.google.com.evil.example/maps/embed",  # host that only starts like one
        "javascript:alert(1)",
        "https://evil.example/?u=https://www.google.com/maps/embed",
    ],
)
def test_a_map_is_only_an_embed_page_of_a_known_map_site(value):
    with pytest.raises(ValidationError):
        validate_map_embed(value)


def test_the_settings_form_checks_the_map_and_the_link():
    site = SiteSettings.load()
    site.map_embed_url = "https://evil.example/x"
    site.announcement_link = "javascript:alert(1)"
    with pytest.raises(ValidationError) as caught:
        site.full_clean()
    assert set(caught.value.message_dict) == {"map_embed_url", "announcement_link"}


def test_a_platform_can_be_listed_once():
    make_link("facebook")
    with pytest.raises(ValidationError):
        SocialLink(site=SiteSettings.load(), platform="facebook", url="https://x.example").validate_constraints()


def test_a_social_link_is_http_or_https_only():
    link = SocialLink(site=SiteSettings.load(), platform="x", url="javascript:alert(1)")
    with pytest.raises(ValidationError) as caught:
        link.full_clean()
    assert "url" in caught.value.message_dict


# --- trust badges -----------------------------------------------------------------------------------------
def test_badges_are_ordered_by_order_then_id():
    make_badge("delivery", "Free delivery", order=1)
    make_badge("returns", "Easy returns", order=0)
    assert list(TrustBadge.objects.values_list("title", flat=True)) == ["Easy returns", "Free delivery"]


def test_a_badge_is_shown_as_its_title():
    badge = make_badge("secure_payment", "Secure payment")
    assert str(badge) == "Secure payment"


# --- pages ------------------------------------------------------------------------------------------------
def test_a_page_body_is_cleaned_when_it_is_saved():
    page = make_page(body='<h2>Hi</h2><script>alert(1)</script><p onclick="x()">Text <a href="javascript:evil()">l</a></p>')
    page.refresh_from_db()
    assert "<script" not in page.body and "onclick" not in page.body and "javascript:" not in page.body
    assert "<h2>Hi</h2>" in page.body and "Text" in page.body


def test_a_slug_is_unique():
    make_page("terms")
    with pytest.raises(IntegrityError), transaction.atomic():
        make_page("terms")


def test_pages_are_ordered_by_order_then_title():
    make_page("b", "B", order=2)
    make_page("a", "A", order=2)
    make_page("c", "C", order=1)
    assert list(StaticPage.objects.values_list("slug", flat=True)) == ["c", "a", "b"]


# --- what visitors send -----------------------------------------------------------------------------------
def test_a_subscriber_email_is_stored_lower_case_and_is_unique_whatever_its_case():
    NewsletterSubscriber.objects.create(email="  Shafayet@Example.COM ")
    assert NewsletterSubscriber.objects.get().email == "shafayet@example.com"
    with pytest.raises(IntegrityError), transaction.atomic():
        NewsletterSubscriber.objects.bulk_create([NewsletterSubscriber(email="SHAFAYET@example.com")])


def test_a_contact_message_starts_unhandled():
    message = ContactMessage.objects.create(name="A", email="a@example.com", message="Hello there")
    assert message.is_handled is False
    assert str(message) == "A: Hello there"
