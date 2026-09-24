from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.catalog.tests.helpers import make_category, make_product
from apps.content.models import ContentItem, Page, Placement
from apps.content.services import page_content

pytestmark = pytest.mark.django_db


def seed(*args):
    out = StringIO()
    call_command("seed_content", *args, stdout=out)
    return out.getvalue()


@pytest.fixture
def catalog(settings):
    settings.DEBUG = True  # the command refuses to run otherwise
    for index in range(3):
        make_product(f"Product {index}")
        make_category(f"Category {index}")


def test_every_page_gets_sliders_and_a_right_banner(catalog):
    seed()
    for page in Page.values:
        content = page_content(page)
        assert len(content["image_sliders"]) == 3, page
        assert content["right_banner"] is not None, page
    assert page_content("home")["left_banner"] is not None
    assert page_content("feature")["left_banner"] is None


def test_the_home_banners_link_to_products_because_the_frontend_only_draws_those_links(catalog):
    seed()
    home = page_content("home")
    assert home["left_banner"]["type"] == home["right_banner"]["type"] == "product"


def test_running_it_again_leaves_filled_pages_alone(catalog):
    seed()
    before = ContentItem.objects.count()
    assert "0 new" in seed()
    assert ContentItem.objects.count() == before


def test_flush_starts_over_and_removes_the_old_pictures(catalog, django_capture_on_commit_callbacks):
    seed()
    old = ContentItem.objects.first()
    storage, name = old.media.storage, old.media.name
    with django_capture_on_commit_callbacks(execute=True):
        seed("--flush")
    assert not storage.exists(name)
    assert ContentItem.objects.count() == 25
    assert ContentItem.objects.filter(placement=Placement.LEFT_BANNER).count() == 1


def test_it_refuses_to_run_without_debug_unless_forced(catalog, settings):
    settings.DEBUG = False
    with pytest.raises(CommandError, match="DEBUG"):
        seed()
    seed("--force")
    assert ContentItem.objects.exists()


def test_it_needs_products_and_categories_to_link_to(settings):
    settings.DEBUG = True
    with pytest.raises(CommandError, match="seed_catalog"):
        seed()
