import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.reviews.models import Review, ReviewMedia
from apps.reviews.tests.helpers import image_upload, other_customer, review_by, reviewers, stocked, video_upload

pytestmark = pytest.mark.django_db

LIST_URL = reverse("admin:reviews_review_changelist")


@pytest.fixture
def admin_client():
    staff = get_user_model().objects.create_superuser("+8801700000000", password="s3cret-Pass!", name="Root")
    client = Client()
    client.force_login(staff)
    return client


@pytest.fixture
def product():
    return stocked("Mug")[0]


def change_url(review):
    return reverse("admin:reviews_review_change", args=[review.pk])


def rating_of(product):
    product.refresh_from_db()
    return product.total_reviews, float(product.avg_rating)


def test_the_list_shows_reviews_with_their_product_and_author(admin_client, product):
    review_by(other_customer(1), product, 4, "A comment that is longer than sixty characters, so the list shortens it.")

    response = admin_client.get(LIST_URL)

    assert response.status_code == 200
    html = response.content.decode()
    assert "Mug" in html and "Customer" not in html.split("<tbody>")[0]  # no stray placeholder in the header
    assert "..." in html  # the long comment is cut


def test_search_by_product_author_phone_and_comment(admin_client, product):
    user = other_customer(1)
    review_by(user, product, 4, "Lovely handle")
    for term in ("Mug", "Lovely", user.phone_number, user.name):
        assert Review.objects.count() == 1
        assert "Lovely handle" in admin_client.get(LIST_URL, {"q": term}).content.decode(), term
    assert "Lovely handle" not in admin_client.get(LIST_URL, {"q": "zzzzz"}).content.decode()


def test_the_filters_work(admin_client, product):
    reviewers(2, product, [5, 1])
    Review.objects.filter(rating=1).update(is_approved=False)
    assert admin_client.get(LIST_URL, {"is_approved__exact": "0"}).status_code == 200
    assert admin_client.get(LIST_URL, {"rating__exact": "5"}).status_code == 200


def test_staff_can_not_add_a_review(admin_client):
    assert admin_client.get(reverse("admin:reviews_review_add")).status_code == 403


def test_the_text_and_rating_are_read_only_only_approval_is_editable(admin_client, product):
    review = review_by(other_customer(1), product, 4, "Original")

    page = admin_client.get(change_url(review)).content.decode()
    assert 'name="is_approved"' in page
    for field in ("rating", "comment", "product", "user"):
        assert f'name="{field}"' not in page

    inlines = {
        "media-TOTAL_FORMS": "0",
        "media-INITIAL_FORMS": "0",
        "media-MIN_NUM_FORMS": "0",
        "media-MAX_NUM_FORMS": "0",
    }
    admin_client.post(change_url(review), {"rating": 1, "comment": "Hacked", **inlines})  # is_approved absent = off
    review.refresh_from_db()
    assert (review.rating, review.comment, review.is_approved) == (4, "Original", False)


def test_unticking_approval_in_the_form_recounts_the_product(admin_client, product):
    reviewers(2, product, [5, 1])
    low = Review.objects.get(rating=1)
    inlines = {"media-TOTAL_FORMS": "0", "media-INITIAL_FORMS": "0", "media-MIN_NUM_FORMS": "0", "media-MAX_NUM_FORMS": "0"}

    response = admin_client.post(change_url(low), {**inlines})  # the box is unticked

    assert response.status_code == 302
    assert rating_of(product) == (1, 5.0)
    assert admin_client.post(change_url(low), {"is_approved": "on", **inlines}).status_code == 302
    assert rating_of(product) == (2, 3.0)


def test_the_hide_and_show_actions_recount_every_product_they_touch(admin_client):
    mug, plate = stocked("Mug")[0], stocked("Plate")[0]
    reviewers(2, mug, [5, 1])
    review_by(other_customer(1), plate, 2)
    ids = [str(pk) for pk in Review.objects.filter(rating__lte=2).values_list("pk", flat=True)]

    response = admin_client.post(LIST_URL, {"action": "hide", "_selected_action": ids}, follow=True)

    assert "2 review(s) hidden." in [str(m) for m in response.context["messages"]]
    assert Review.objects.filter(is_approved=False).count() == 2
    assert rating_of(mug) == (1, 5.0) and rating_of(plate) == (0, 0.0)

    admin_client.post(LIST_URL, {"action": "show", "_selected_action": ids})
    assert rating_of(mug) == (2, 3.0) and rating_of(plate) == (1, 2.0)


def test_deleting_from_the_admin_recounts(admin_client, product):
    reviewers(2, product, [5, 1])
    low = Review.objects.get(rating=1)

    response = admin_client.post(reverse("admin:reviews_review_delete", args=[low.pk]), {"post": "yes"})

    assert response.status_code == 302 and Review.objects.count() == 1
    assert rating_of(product) == (1, 5.0)


def test_bulk_delete_from_the_admin_recounts(admin_client, product):
    reviewers(3, product, [5, 1, 1])
    ids = [str(pk) for pk in Review.objects.filter(rating=1).values_list("pk", flat=True)]

    admin_client.post(LIST_URL, {"action": "delete_selected", "_selected_action": ids, "post": "yes"})

    assert Review.objects.count() == 1 and rating_of(product) == (1, 5.0)


def test_the_page_shows_the_photos_and_videos_and_staff_can_remove_one(admin_client, product):
    review = review_by(other_customer(1), product)
    photo = ReviewMedia.objects.create(review=review, file=image_upload())
    clip = ReviewMedia.objects.create(review=review, file=video_upload())

    page = admin_client.get(change_url(review)).content.decode()
    assert photo.file.url in page and clip.file.url in page and "video</a>" in page

    inlines = {
        "media-TOTAL_FORMS": "2",
        "media-INITIAL_FORMS": "2",
        "media-MIN_NUM_FORMS": "0",
        "media-MAX_NUM_FORMS": "1000",
        "media-0-id": str(photo.pk),
        "media-0-review": str(review.pk),
        "media-0-DELETE": "on",
        "media-1-id": str(clip.pk),
        "media-1-review": str(review.pk),
        "is_approved": "on",
    }
    assert admin_client.post(change_url(review), inlines).status_code == 302
    assert list(review.media.all()) == [clip]
