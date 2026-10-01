import csv
import io

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.siteconfig.models import ContactMessage, NewsletterSubscriber, SiteSettings, StaticPage

from .helpers import make_link, make_page, make_settings

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client():
    user = get_user_model().objects.create_superuser("+8801700000000", password="s3cret-Pass!", name="Root")
    client = Client()
    client.force_login(user)
    return client


def settings_form(**overrides):
    data = {
        "site_name": "GoCart",
        "tagline": "",
        "announcement_text": "",
        "announcement_link": "",
        "contact_email": "",
        "contact_phone": "",
        "contact_address": "",
        "opening_hours": "",
        "map_embed_url": "",
        "social_links-TOTAL_FORMS": "0",
        "social_links-INITIAL_FORMS": "0",
        "social_links-MIN_NUM_FORMS": "0",
        "social_links-MAX_NUM_FORMS": "1000",
        "trust_badges-TOTAL_FORMS": "0",
        "trust_badges-INITIAL_FORMS": "0",
        "trust_badges-MIN_NUM_FORMS": "0",
        "trust_badges-MAX_NUM_FORMS": "1000",
    }
    return data | overrides


# --- site settings -----------------------------------------------------------------------------------------
def test_the_menu_entry_opens_the_one_row_and_creates_it(admin_client):
    assert SiteSettings.objects.count() == 0
    response = admin_client.get(reverse("admin:siteconfig_sitesettings_changelist"))
    assert response.status_code == 302
    assert response.url == reverse("admin:siteconfig_sitesettings_change", args=[1])
    assert admin_client.get(response.url).status_code == 200
    assert SiteSettings.objects.count() == 1


def test_no_second_row_can_be_added_and_the_row_can_not_be_deleted(admin_client):
    make_settings()
    assert admin_client.get(reverse("admin:siteconfig_sitesettings_add")).status_code == 403
    assert admin_client.get(reverse("admin:siteconfig_sitesettings_delete", args=[1])).status_code == 403


def test_the_settings_are_saved(admin_client):
    make_settings()
    response = admin_client.post(
        reverse("admin:siteconfig_sitesettings_change", args=[1]),
        settings_form(site_name="My Own Shop", announcement_enabled="on", announcement_text="Sale", announcement_link="/products/flash-sale"),
    )
    assert response.status_code == 302
    site = SiteSettings.load()
    assert (site.site_name, site.announcement_enabled, site.announcement_link) == ("My Own Shop", True, "/products/flash-sale")


def test_the_bar_can_be_given_an_end_and_it_can_be_emptied_again(admin_client):
    make_settings()
    url = reverse("admin:siteconfig_sitesettings_change", args=[1])
    on = settings_form(announcement_enabled="on", announcement_text="Sale", announcement_ends_at_0="2030-10-03", announcement_ends_at_1="23:59:59")
    assert admin_client.post(url, on).status_code == 302
    ends_at = SiteSettings.load().announcement_ends_at
    assert ends_at is not None and ends_at.year == 2030 and ends_at.month == 10
    assert admin_client.post(url, on | {"announcement_ends_at_0": "", "announcement_ends_at_1": ""}).status_code == 302
    assert SiteSettings.load().announcement_ends_at is None  # empty: until it is switched off


def test_a_bad_link_or_map_is_said_in_the_form_and_nothing_is_saved(admin_client):
    make_settings(site_name="Before")
    response = admin_client.post(
        reverse("admin:siteconfig_sitesettings_change", args=[1]),
        settings_form(site_name="After", announcement_link="javascript:alert(1)", map_embed_url="https://evil.example/x"),
    )
    assert response.status_code == 200
    assert response.context["adminform"].form.errors.keys() == {"announcement_link", "map_embed_url"}
    assert SiteSettings.load().site_name == "Before"


def test_social_links_are_edited_on_the_same_page(admin_client):
    make_settings()
    form = settings_form(**{
        "social_links-TOTAL_FORMS": "1",
        "social_links-0-platform": "instagram",
        "social_links-0-url": "https://instagram.com/shop",
        "social_links-0-order": "0",
        "social_links-0-is_active": "on",
    })
    assert admin_client.post(reverse("admin:siteconfig_sitesettings_change", args=[1]), form).status_code == 302
    assert SiteSettings.load().social_links.get().url == "https://instagram.com/shop"


def test_trust_badges_are_edited_on_the_same_page(admin_client):
    make_settings()
    form = settings_form(**{
        "trust_badges-TOTAL_FORMS": "1",
        "trust_badges-0-icon": "delivery",
        "trust_badges-0-title": "Free delivery",
        "trust_badges-0-subtitle": "",
        "trust_badges-0-order": "0",
        "trust_badges-0-is_active": "on",
    })
    assert admin_client.post(reverse("admin:siteconfig_sitesettings_change", args=[1]), form).status_code == 302
    assert SiteSettings.load().trust_badges.get().title == "Free delivery"


def test_a_platform_twice_is_refused_in_the_form(admin_client):
    make_settings()
    form = settings_form(**{
        "social_links-TOTAL_FORMS": "2",
        "social_links-0-platform": "x", "social_links-0-url": "https://x.com/a", "social_links-0-order": "0",
        "social_links-1-platform": "x", "social_links-1-url": "https://x.com/b", "social_links-1-order": "1",
    })
    response = admin_client.post(reverse("admin:siteconfig_sitesettings_change", args=[1]), form)
    assert response.status_code == 200
    assert SiteSettings.load().social_links.count() == 0


# --- pages -------------------------------------------------------------------------------------------------
def test_a_page_written_in_the_admin_is_cleaned_of_scripts(admin_client):
    response = admin_client.post(
        reverse("admin:siteconfig_staticpage_add"),
        {"slug": "terms", "title": "Terms", "body": "<p>ok</p><script>alert(1)</script>", "is_published": "on", "footer_group": "legal", "order": "1"},
    )
    assert response.status_code == 302
    assert StaticPage.objects.get(slug="terms").body == "<p>ok</p>"


def test_the_page_list_can_be_edited_in_place(admin_client):
    page = make_page("about-us", "About Us", is_published=True)
    response = admin_client.post(
        reverse("admin:siteconfig_staticpage_changelist"),
        {
            "form-TOTAL_FORMS": "1", "form-INITIAL_FORMS": "1", "form-MIN_NUM_FORMS": "0", "form-MAX_NUM_FORMS": "1000",
            "form-0-id": str(page.pk), "form-0-footer_group": "company", "form-0-order": "3",
            "_save": "Save",
        },
    )
    assert response.status_code == 302
    page.refresh_from_db()
    assert (page.is_published, page.footer_group, page.order) == (False, "company", 3)  # unticked = taken offline


# --- messages ----------------------------------------------------------------------------------------------
def test_messages_can_be_read_and_marked_handled_but_not_written_or_edited(admin_client):
    message = ContactMessage.objects.create(name="A", email="a@example.com", message="Hello there")
    assert admin_client.get(reverse("admin:siteconfig_contactmessage_add")).status_code == 403
    page = admin_client.get(reverse("admin:siteconfig_contactmessage_change", args=[message.pk]))
    assert page.status_code == 200 and b"Hello there" in page.content
    admin_client.post(
        reverse("admin:siteconfig_contactmessage_changelist"),
        {"action": "mark_handled", "_selected_action": [message.pk]},
    )
    message.refresh_from_db()
    assert message.is_handled is True
    admin_client.post(
        reverse("admin:siteconfig_contactmessage_change", args=[message.pk]),
        {"name": "Changed", "message": "Changed", "is_handled": ""},
    )
    message.refresh_from_db()
    assert (message.name, message.message, message.is_handled) == ("A", "Hello there", False)  # only the tick is editable


def test_a_message_is_shown_as_text_never_as_markup(admin_client):
    message = ContactMessage.objects.create(name="A", email="a@example.com", message="<script>alert(1)</script>")
    body = admin_client.get(reverse("admin:siteconfig_contactmessage_change", args=[message.pk])).content.decode()
    assert "<script>alert(1)</script>" not in body and "&lt;script&gt;" in body


# --- newsletter --------------------------------------------------------------------------------------------
def test_subscribers_are_exported_as_csv(admin_client):
    NewsletterSubscriber.objects.create(email="a@example.com")
    NewsletterSubscriber.objects.create(email="b@example.com", is_active=False)
    ids = list(NewsletterSubscriber.objects.values_list("pk", flat=True))
    response = admin_client.post(
        reverse("admin:siteconfig_newslettersubscriber_changelist"), {"action": "export_csv", "_selected_action": ids}
    )
    assert response["Content-Type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(response.content.decode())))
    assert rows[0] == ["email", "active", "subscribed_at"]
    assert [(row[0], row[1]) for row in rows[1:]] == [("a@example.com", "yes"), ("b@example.com", "no")]


def test_subscribers_can_be_switched_off_and_on(admin_client):
    subscriber = NewsletterSubscriber.objects.create(email="a@example.com")
    url = reverse("admin:siteconfig_newslettersubscriber_changelist")
    admin_client.post(url, {"action": "deactivate", "_selected_action": [subscriber.pk]})
    subscriber.refresh_from_db()
    assert subscriber.is_active is False
    admin_client.post(url, {"action": "activate", "_selected_action": [subscriber.pk]})
    subscriber.refresh_from_db()
    assert subscriber.is_active is True


def test_every_admin_page_opens(admin_client):
    make_settings()
    make_link()
    for name in ("sitesettings", "staticpage", "faqitem", "contactmessage", "newslettersubscriber"):
        assert admin_client.get(reverse(f"admin:siteconfig_{name}_changelist"), follow=True).status_code == 200
