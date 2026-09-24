import pytest
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction

from apps.catalog.tests.helpers import MP4, image_file, make_category, make_product
from apps.content.models import ContentItem, LinkType, Page, PageContent, Placement
from apps.content.tests.helpers import get_page, make_item

pytestmark = pytest.mark.django_db


def unsaved(placement=Placement.IMAGE_SLIDER, page=Page.HOME, video=False, **kwargs):
    media = ContentFile(MP4, name="clip.mp4") if video else image_file()
    return ContentItem(page=get_page(page), placement=placement, media=media, **kwargs)


def errors_of(item):
    with pytest.raises(ValidationError) as caught:
        item.full_clean()
    return caught.value.message_dict


# --- pages ---------------------------------------------------------------------------------------------
def test_a_migration_creates_the_six_pages_the_frontend_asks_for():
    assert set(PageContent.objects.values_list("page", flat=True)) == {
        "home", "newarrival", "flashsale", "best_selling", "feature", "category",
    }  # fmt: skip
    assert set(Page.values) == set(PageContent.objects.values_list("page", flat=True))


def test_a_page_exists_once():
    with pytest.raises(IntegrityError), transaction.atomic():
        PageContent.objects.create(page=Page.HOME)


# --- what an item links to -------------------------------------------------------------------------------
def test_a_product_link_needs_a_product():
    assert "product" in errors_of(unsaved(link_type=LinkType.PRODUCT))


def test_a_category_link_needs_a_category():
    assert "category" in errors_of(unsaved(link_type=LinkType.CATEGORY))


def test_an_external_link_needs_an_address():
    assert "external_link" in errors_of(unsaved(link_type=LinkType.EXTERNAL))


@pytest.mark.parametrize(
    "address", ["javascript:alert(1)", "ftp://example.com/file", "data:text/html,x", "example.com", "//example.com"]
)
def test_an_external_address_must_be_http_or_https(address):
    item = unsaved(link_type=LinkType.EXTERNAL, external_link=address)
    assert "external_link" in errors_of(item)


@pytest.mark.parametrize("address", ["https://example.com/sale", "http://example.com"])
def test_a_valid_external_address_is_accepted(address):
    unsaved(link_type=LinkType.EXTERNAL, external_link=address).full_clean()


def test_what_does_not_apply_to_the_link_type_is_dropped():
    product, category = make_product("P"), make_category("C")
    item = unsaved(link_type=LinkType.CATEGORY, product=product, category=category, external_link="https://x.example")
    item.full_clean()
    item.save()
    item.refresh_from_db()
    assert (item.product, item.category, item.external_link) == (None, category, "")


def test_link_is_the_slug_of_the_target_and_none_for_another_site():
    product, category = make_product("Blue Shirt"), make_category("Shirts")
    assert make_item(target=product).link == "blue-shirt"
    assert make_item(target=category).link == "shirts"
    assert make_item(link_type=LinkType.EXTERNAL, external_link="https://example.com").link is None


def test_the_database_refuses_a_link_that_does_not_match_its_type():
    item = make_item()
    with pytest.raises(IntegrityError), transaction.atomic():
        ContentItem.objects.filter(pk=item.pk).update(link_type=LinkType.EXTERNAL)  # no address, still a product


# --- the media -------------------------------------------------------------------------------------------
def test_the_media_type_is_read_from_the_file_not_typed_in():
    assert make_item().media_type == "image"
    assert make_item(placement=Placement.VIDEO_SLIDER, video=True).media_type == "video"


def test_a_file_that_is_neither_image_nor_video_is_refused():
    item = ContentItem(
        page=get_page(), placement=Placement.IMAGE_SLIDER, media=ContentFile(b"not media", name="x.txt"),
        link_type=LinkType.EXTERNAL, external_link="https://example.com",
    )  # fmt: skip
    assert "media" in errors_of(item)


@pytest.mark.parametrize(
    ("placement", "video"),
    [
        (Placement.IMAGE_SLIDER, True),
        (Placement.LEFT_BANNER, True),
        (Placement.VIDEO_SLIDER, False),
    ],
)
def test_a_placement_only_takes_the_media_it_can_show(placement, video):
    item = unsaved(placement=placement, video=video, link_type=LinkType.EXTERNAL, external_link="https://example.com")
    assert "media" in errors_of(item)
    with pytest.raises(ValidationError):  # and save() does not let it through either
        item.save()


@pytest.mark.parametrize("video", [True, False])
def test_the_right_banner_takes_either(video):
    unsaved(placement=Placement.RIGHT_BANNER, video=video, link_type=LinkType.EXTERNAL, external_link="https://example.com").full_clean()


def test_changing_the_placement_of_an_existing_image_to_a_video_slider_is_caught():
    item = make_item()
    item.placement = Placement.VIDEO_SLIDER
    assert "media" in errors_of(item)


# --- one banner per side -------------------------------------------------------------------------------
def test_a_page_has_one_active_banner_per_side():
    make_item(placement=Placement.RIGHT_BANNER)
    with pytest.raises(IntegrityError), transaction.atomic():
        make_item(placement=Placement.RIGHT_BANNER)


def test_the_form_check_says_so_before_the_database_does():
    make_item(placement=Placement.RIGHT_BANNER)
    second = unsaved(placement=Placement.RIGHT_BANNER, link_type=LinkType.EXTERNAL, external_link="https://example.com")
    assert "__all__" in errors_of(second)


def test_a_spare_inactive_banner_is_fine():
    make_item(placement=Placement.RIGHT_BANNER)
    make_item(placement=Placement.RIGHT_BANNER, is_active=False)
    make_item(placement=Placement.RIGHT_BANNER, is_active=False)
    assert ContentItem.objects.filter(placement=Placement.RIGHT_BANNER).count() == 3


def test_the_other_side_and_the_other_pages_are_independent():
    make_item(placement=Placement.RIGHT_BANNER)
    make_item(placement=Placement.LEFT_BANNER)
    make_item(page=Page.FLASH_SALE, placement=Placement.RIGHT_BANNER)


def test_sliders_are_not_limited():
    for _ in range(4):
        make_item(placement=Placement.IMAGE_SLIDER)
    assert ContentItem.objects.filter(placement=Placement.IMAGE_SLIDER).count() == 4


# --- cleanup ---------------------------------------------------------------------------------------------
def test_deleting_an_item_removes_its_file(django_capture_on_commit_callbacks):
    item = make_item()
    storage, name = item.media.storage, item.media.name
    assert storage.exists(name)
    with django_capture_on_commit_callbacks(execute=True):
        item.delete()
    assert not storage.exists(name)


def test_replacing_the_media_removes_the_old_file(django_capture_on_commit_callbacks):
    item = make_item()
    storage, old = item.media.storage, item.media.name
    with django_capture_on_commit_callbacks(execute=True):
        item.media = image_file(name="new.png")
        item.save()
    assert not storage.exists(old)
    assert storage.exists(item.media.name)


def test_deleting_a_product_or_category_takes_its_slides_with_it():
    product, category = make_product("P"), make_category("C")
    on_product, on_category = make_item(target=product), make_item(target=category)
    other = make_item(link_type=LinkType.EXTERNAL, external_link="https://example.com")

    product.delete()
    category.delete()

    assert set(ContentItem.objects.values_list("pk", flat=True)) == {other.pk}
    assert not ContentItem.objects.filter(pk__in=[on_product.pk, on_category.pk]).exists()


def test_str_names_the_placement_and_page():
    assert str(make_item(placement=Placement.LEFT_BANNER, order=2)) == "Left banner #2 (Home)"
    assert str(get_page(Page.BEST_SELLING)) == "Best selling"
