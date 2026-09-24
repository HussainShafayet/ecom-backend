import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from apps.catalog.tests.helpers import image_bytes, make_product
from apps.content.models import ContentItem, Page, Placement
from apps.content.tests.helpers import get_page, make_item

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client():
    user = get_user_model().objects.create_superuser("+8801700000000", password="s3cret-Pass!", name="Root")
    client = Client()
    client.force_login(user)
    return client


def change_url(page=Page.HOME):
    return reverse("admin:content_pagecontent_change", args=[get_page(page).pk])


def form_data(rows):
    """The POST an admin sends for the inline formset: `rows` are (placement, is_active) of NEW items."""
    product = make_product("Linked")
    data = {
        "items-TOTAL_FORMS": str(len(rows)),
        "items-INITIAL_FORMS": "0",
        "items-MIN_NUM_FORMS": "0",
        "items-MAX_NUM_FORMS": "1000",
    }
    for index, (placement, is_active) in enumerate(rows):
        prefix = f"items-{index}-"
        data |= {
            prefix + "placement": placement,
            prefix + "order": str(index),
            prefix + "link_type": "product",
            prefix + "product": str(product.pk),
            prefix + "caption": f"item {index}",
            prefix + "media": SimpleUploadedFile(f"banner{index}.png", image_bytes(size=(20, 20))),
        }
        if is_active:
            data[prefix + "is_active"] = "on"
    return data


def test_the_six_pages_are_listed_and_openable(admin_client):
    listing = admin_client.get(reverse("admin:content_pagecontent_changelist"))
    assert listing.status_code == 200
    for label in ("Home", "New arrivals", "Flash sale", "Best selling", "Featured", "Categories"):
        assert label in listing.content.decode()
    assert admin_client.get(change_url()).status_code == 200


def test_the_change_page_shows_existing_items_with_a_preview(admin_client):
    make_item(placement=Placement.IMAGE_SLIDER)
    make_item(placement=Placement.VIDEO_SLIDER, video=True)
    html = admin_client.get(change_url()).content.decode()
    assert "<img" in html and "<video" in html


def test_pages_can_neither_be_added_nor_deleted(admin_client):
    assert admin_client.get(reverse("admin:content_pagecontent_add")).status_code == 403
    assert admin_client.get(reverse("admin:content_pagecontent_delete", args=[get_page().pk])).status_code == 403


def test_two_active_banners_on_one_side_are_refused_with_a_message(admin_client):
    response = admin_client.post(
        change_url(), form_data([(Placement.RIGHT_BANNER, True), (Placement.RIGHT_BANNER, True)])
    )
    assert response.status_code == 200  # the form again, no redirect
    assert "Only one active right banner is allowed" in response.content.decode()
    assert not ContentItem.objects.exists()


def test_a_spare_inactive_banner_is_accepted(admin_client):
    response = admin_client.post(
        change_url(), form_data([(Placement.RIGHT_BANNER, True), (Placement.RIGHT_BANNER, False)])
    )
    assert response.status_code == 302, response.content.decode()[:2000]
    assert ContentItem.objects.count() == 2


def test_two_sliders_are_accepted_and_get_their_media_type(admin_client):
    response = admin_client.post(
        change_url(), form_data([(Placement.IMAGE_SLIDER, True), (Placement.IMAGE_SLIDER, True)])
    )
    assert response.status_code == 302
    assert set(ContentItem.objects.values_list("media_type", flat=True)) == {"image"}


def test_a_video_in_an_image_slider_is_refused_in_the_form(admin_client):
    data = form_data([(Placement.IMAGE_SLIDER, True)])
    data["items-0-media"] = SimpleUploadedFile("clip.mp4", b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 64)
    response = admin_client.post(change_url(), data)
    assert response.status_code == 200
    assert "needs an image" in response.content.decode()
    assert not ContentItem.objects.exists()
