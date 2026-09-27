import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.siteconfig.models import FaqItem, SiteSettings, SocialLink, StaticPage

from .helpers import make_faq, make_page, make_settings

pytestmark = pytest.mark.django_db


def seed(**options):
    call_command("seed_site", **options)


def test_it_fills_an_empty_shop(settings):
    settings.DEBUG = True
    seed()
    site = SiteSettings.load()
    assert site.site_name == "GoCart" and site.announcement_enabled and site.announcement_link == "/products/flash-sale"
    assert SocialLink.objects.count() == 2
    assert set(StaticPage.objects.values_list("slug", flat=True)) == {"about-us", "privacy-policy", "terms-of-service", "cookie-policy"}
    assert FaqItem.objects.count() == 5


def test_what_it_writes_passes_the_models_own_checks(settings):
    settings.DEBUG = True
    seed()
    SiteSettings.load().full_clean()
    for link in SocialLink.objects.all():
        link.full_clean()
    for page in StaticPage.objects.all():
        page.full_clean()
        assert "<script" not in page.body


def test_running_it_twice_changes_nothing(settings):
    settings.DEBUG = True
    seed()
    counts = (SocialLink.objects.count(), StaticPage.objects.count(), FaqItem.objects.count())
    seed()
    assert (SocialLink.objects.count(), StaticPage.objects.count(), FaqItem.objects.count()) == counts


def test_a_shop_that_has_its_own_content_keeps_it(settings):
    settings.DEBUG = True
    make_settings(site_name="Mine")
    make_page("about-us", "My about", "<p>Mine</p>")
    make_faq("My question?", "Mine.")
    seed()
    assert SiteSettings.load().site_name == "Mine" and SocialLink.objects.count() == 0
    assert StaticPage.objects.get(slug="about-us").body == "<p>Mine</p>"
    assert list(FaqItem.objects.values_list("question", flat=True)) == ["My question?"]
    assert StaticPage.objects.count() == 4  # only the pages it lacked were added


def test_it_refuses_to_run_with_debug_off_unless_forced(settings):
    settings.DEBUG = False
    with pytest.raises(CommandError):
        seed()
    assert SiteSettings.objects.count() == 0
    seed(force=True)
    assert SiteSettings.objects.count() == 1
