"""What the database itself guarantees, whatever code writes to it."""
import pytest
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction

from apps.catalog.models import Product
from apps.reviews.models import Review, ReviewMedia
from apps.reviews.tests.helpers import (
    delivered_order,
    image_upload,
    other_customer,
    review_by,
    signed_in,
    stocked,
    video_upload,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def shop():
    product, _ = stocked("Mug")
    return product, other_customer(1)


@pytest.mark.parametrize("rating", [0, 6, 100])
def test_a_rating_outside_1_to_5_is_refused_by_the_database(shop, rating):
    product, user = shop
    with pytest.raises(IntegrityError), transaction.atomic():
        Review.objects.create(product=product, user=user, rating=rating, comment="x")


def test_an_empty_comment_is_refused_by_the_database(shop):
    product, user = shop
    with pytest.raises(IntegrityError), transaction.atomic():
        Review.objects.create(product=product, user=user, rating=3, comment="")


def test_one_review_per_customer_and_product(shop):
    product, user = shop
    review_by(user, product)
    with pytest.raises(IntegrityError), transaction.atomic():
        review_by(user, product, rating=1)
    other, _ = stocked("Plate")
    review_by(user, other)  # another product is fine
    review_by(other_customer(2), product)  # another customer is fine


def test_deleting_the_product_deletes_its_reviews_and_their_files(shop, django_capture_on_commit_callbacks):
    product, user = shop
    review = review_by(user, product)
    ReviewMedia.objects.create(review=review, file=image_upload())
    (name,) = [item.file.name for item in ReviewMedia.objects.all()]
    assert default_storage.exists(name)

    with django_capture_on_commit_callbacks(execute=True):
        product.delete()

    assert Review.objects.count() == 0 and not default_storage.exists(name)


def test_deleting_the_purchase_line_keeps_the_review():
    product, variant = stocked("Mug")
    user, _ = signed_in()
    item = delivered_order(user, product, variant).items.get()
    review = review_by(user, product, order_item=item)

    item.delete()

    review.refresh_from_db()
    assert review.order_item is None


def test_a_review_needs_no_order_at_the_database_level(shop):
    """The delivered-order rule is enforced by the service (the only writer), not by a column."""
    product, user = shop
    assert review_by(user, product).order_item is None


def test_the_customer_can_be_deleted_with_their_reviews(shop):
    product, user = shop
    review_by(user, product)
    user.delete()
    assert Review.objects.count() == 0 and Product.objects.filter(pk=product.pk).exists()


def test_the_media_order_is_the_upload_order(shop):
    product, user = shop
    review = review_by(user, product)
    first = ReviewMedia.objects.create(review=review, file=image_upload("1.png"))
    second = ReviewMedia.objects.create(review=review, file=image_upload("2.png"))
    assert list(review.media.all()) == [first, second]


def test_media_of_an_unsupported_type_can_not_be_saved(shop):
    product, user = shop
    review = review_by(user, product)
    with pytest.raises(ValidationError):
        ReviewMedia.objects.create(review=review, file=SimpleUploadedFile("a.png", b"not an image"))
    assert ReviewMedia.objects.count() == 0


def test_is_video_follows_the_content_type(shop):
    product, user = shop
    review = review_by(user, product)
    photo = ReviewMedia.objects.create(review=review, file=image_upload())
    clip = ReviewMedia.objects.create(review=review, file=video_upload())
    assert (photo.is_video, clip.is_video) == (False, True)


def test_str_forms_are_readable(shop):
    product, user = shop
    review = review_by(user, product, rating=4)
    assert "4/5" in str(review)
    assert str(ReviewMedia(content_type="image/png")).startswith("image/png")
