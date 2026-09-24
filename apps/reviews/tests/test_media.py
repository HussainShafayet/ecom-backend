"""Photos and videos on a review: what is accepted, how it is stored, and that a failure leaves nothing behind."""
import re

import pytest
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.core.validators import detect_media_format
from apps.reviews.models import Review, ReviewMedia
from apps.reviews.tests.helpers import (
    MP4,
    WEBM,
    buyer,
    data,
    edit_review,
    image_upload,
    stocked,
    video_upload,
    write_review,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def shop():
    product, variant = stocked("Mug")
    user, client = buyer(product, variant)
    return product, user, client


def stored_files():
    """Every file below reviews/ in storage."""
    try:
        return default_storage.listdir("reviews")[1]
    except FileNotFoundError:
        return []


def test_photos_and_videos_come_back_as_urls_with_a_mime_type(shop):
    product, _, client = shop

    response = write_review(client, product, media=[image_upload("a.png"), video_upload("b.mp4"), video_upload("c.webm", WEBM)])

    assert response.status_code == 201, response.content
    media = data(response)["media_urls"]
    assert [item["type"] for item in media] == ["image/png", "video/mp4", "video/webm"]
    for item, ext in zip(media, ["png", "mp4", "webm"]):
        assert re.fullmatch(rf"http://testserver/media/reviews/[0-9a-f]{{32}}\.{ext}", item["file"]), item
        assert set(item) == {"file", "type"}


@pytest.mark.parametrize(
    "upload, extension, mime",
    [
        (lambda: image_upload("holiday.JPEG", fmt="JPEG"), "jpg", "image/jpeg"),
        (lambda: image_upload("no-extension", fmt="PNG"), "png", "image/png"),
        (lambda: image_upload("wrong.txt", fmt="WEBP"), "webp", "image/webp"),
        (lambda: video_upload("clip.mov", MP4), "mp4", "video/mp4"),
        (lambda: video_upload("movie", WEBM), "webm", "video/webm"),
    ],
    ids=["jpeg", "no-extension", "webp-named-txt", "mp4-named-mov", "webm-no-extension"],
)
def test_the_stored_name_carries_the_extension_the_bytes_say(shop, upload, extension, mime):
    """The frontend tells an image from a video by the URL's extension, and the browser wants the MIME type."""
    product, _, client = shop

    response = write_review(client, product, media=[upload()])

    item = data(response)["media_urls"][0]
    assert item["file"].endswith(f".{extension}") and item["type"] == mime
    assert ReviewMedia.objects.get().content_type == mime


def test_the_original_file_name_is_never_kept(shop):
    product, _, client = shop
    write_review(client, product, media=[image_upload("my-home-address-12-road-5.png")])
    (name,) = stored_files()
    assert "address" not in name and re.fullmatch(r"[0-9a-f]{32}\.png", name)


@pytest.mark.parametrize(
    "name, upload",
    [
        ("photo.jpg", lambda: SimpleUploadedFile("photo.jpg", b"just text pretending to be a photo")),
        ("page.png", lambda: SimpleUploadedFile("page.png", b"<html><script>alert(1)</script></html>")),
        ("anim.gif", lambda: image_upload("anim.gif", fmt="GIF")),
        ("empty.png", lambda: SimpleUploadedFile("empty.png", b"")),
    ],
    ids=["text-as-jpg", "html-as-png", "gif", "empty"],
)
def test_a_file_that_is_not_a_supported_photo_or_video_is_refused(shop, name, upload):
    product, _, client = shop

    response = write_review(client, product, media=[upload()])

    assert response.status_code == 400, response.content
    (problem,) = response.json()["field_errors"]["media"]
    assert problem.startswith(f"{name}: ")
    assert Review.objects.count() == 0 and stored_files() == []


def test_the_size_limits_apply_per_type(shop, settings):
    product, _, client = shop
    settings.MAX_IMAGE_UPLOAD_MB = 0
    assert write_review(client, product, media=[image_upload()]).status_code == 400
    settings.MAX_VIDEO_UPLOAD_MB = 0
    assert write_review(client, product, media=[video_upload()]).status_code == 400
    settings.MAX_VIDEO_UPLOAD_MB = 1
    assert write_review(client, product, media=[video_upload()]).status_code == 201  # the same bytes as a video: fine


def test_one_bad_file_refuses_the_whole_review(shop):
    product, _, client = shop
    bad = SimpleUploadedFile("x.png", b"nope")
    response = write_review(client, product, media=[image_upload(), bad, image_upload()])
    assert response.status_code == 400
    assert Review.objects.count() == 0 and stored_files() == []


def test_at_most_five_files_and_nothing_is_written_beyond(shop):
    product, _, client = shop
    response = write_review(client, product, media=[image_upload(f"{i}.png") for i in range(6)])
    assert response.status_code == 400
    assert response.json()["field_errors"]["media"] == ["A review can have at most 5 photos or videos."]
    assert Review.objects.count() == 0 and stored_files() == []

    assert write_review(client, product, media=[image_upload(f"{i}.png") for i in range(5)]).status_code == 201
    assert ReviewMedia.objects.count() == 5


def test_too_many_files_are_refused_before_any_is_examined(shop, monkeypatch):
    """A request with a hundred files costs a count, not a hundred content checks."""
    product, _, client = shop
    looked_at = []
    real = detect_media_format

    def spy(file):
        looked_at.append(file.name)
        return real(file)

    monkeypatch.setattr("apps.core.validators.detect_media_format", spy)

    response = write_review(client, product, media=[image_upload(f"{i}.png") for i in range(30)])

    assert response.status_code == 400 and looked_at == []


def test_the_file_limit_is_configurable(shop, settings):
    product, _, client = shop
    settings.MAX_REVIEW_FILES = 1
    assert write_review(client, product, media=[image_upload(), image_upload()]).status_code == 400
    assert write_review(client, product, media=[image_upload()]).status_code == 201


def test_media_sent_as_text_is_not_a_file(shop):
    product, _, client = shop
    response = write_review(client, product, media=["[object Object]", "https://example.com/a.png"])
    assert response.status_code == 201
    assert data(response)["media_urls"] == []


def test_a_json_body_can_not_carry_media(shop):
    product, _, client = shop
    body = {"product_id": product.pk, "rating": 5, "comment": "x", "media": ["a.png"]}
    response = client.post("/api/v1/products/reviews/", body, format="json")
    assert response.status_code == 201 and data(response)["media_urls"] == []


# --- a failure leaves no files behind ---------------------------------------------------------------------------
def test_files_already_written_are_removed_when_the_review_fails_midway(shop, monkeypatch):
    """The second file blows up after the first one reached the storage: the review is rolled back, and the first
    file must not stay behind as an orphan."""
    product, _, client = shop
    real_save = ReviewMedia.save
    calls = []

    def save_then_fail(self, *args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("the disk is full")
        return real_save(self, *args, **kwargs)

    monkeypatch.setattr(ReviewMedia, "save", save_then_fail)
    client.raise_request_exception = False

    response = write_review(client, product, media=[image_upload("1.png"), image_upload("2.png")])

    assert response.status_code == 500
    assert Review.objects.count() == 0 and ReviewMedia.objects.count() == 0
    assert stored_files() == []


def test_a_failed_edit_removes_the_files_it_wrote_and_keeps_the_review(shop, monkeypatch):
    product, _, client = shop
    review_id = data(write_review(client, product, comment="Before", media=[image_upload("kept.png")]))["id"]
    before = stored_files()
    real_save = ReviewMedia.save
    calls = []

    def save_then_fail(self, *args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("the disk is full")
        return real_save(self, *args, **kwargs)

    monkeypatch.setattr(ReviewMedia, "save", save_then_fail)
    client.raise_request_exception = False

    response = edit_review(client, review_id, comment="After", media=[image_upload("2.png"), image_upload("3.png")])

    assert response.status_code == 500
    review = Review.objects.get()
    assert review.comment == "Before" and review.media.count() == 1
    assert stored_files() == before


def test_deleting_a_review_deletes_its_files(shop, django_capture_on_commit_callbacks):
    product, _, client = shop
    write_review(client, product, media=[image_upload(), video_upload()])
    assert len(stored_files()) == 2

    with django_capture_on_commit_callbacks(execute=True):
        Review.objects.get().delete()

    assert stored_files() == []
