"""PUT /products/reviews/{id}/: the author edits their own review."""
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.reviews.models import Review, ReviewMedia
from apps.reviews.tests.helpers import (
    REVIEWS,
    authed_client,
    buyer,
    data,
    edit_review,
    image_upload,
    other_customer,
    review_by,
    stocked,
    video_upload,
    write_review,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def shop():
    """(product, user, client, review_id): a buyer who has written a 3-star review."""
    product, variant = stocked("Mug")
    user, client = buyer(product, variant)
    review_id = data(write_review(client, product, rating=3, comment="It is ok."))["id"]
    return product, user, client, review_id


def test_the_author_changes_the_rating_and_the_comment(shop):
    product, user, client, review_id = shop

    response = edit_review(client, review_id, product_id=product.pk, rating=5, comment="Better than I thought.")

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["success"] is True and body["message"] == "Review updated."
    assert (body["data"]["id"], body["data"]["rating"], body["data"]["comment"]) == (
        review_id,
        5,
        "Better than I thought.",
    )
    assert body["data"]["can_edited"] is True
    review = Review.objects.get()
    assert (review.rating, review.comment) == (5, "Better than I thought.")


def test_the_frontends_edit_request_works(shop):
    """What RatingAndReview sends: product_id, rating, comment, and the existing media as `[object Object]`."""
    product, _, client, review_id = shop
    body = {
        "product_id": product.pk,
        "rating": 4,
        "comment": "Edited",
        "media": ["[object Object]", "[object Object]"],
    }

    response = client.put(f"{REVIEWS}{review_id}/", body, format="multipart")

    assert response.status_code == 200, response.content
    assert Review.objects.get().rating == 4 and ReviewMedia.objects.count() == 0


def test_every_field_is_optional(shop):
    _, _, client, review_id = shop
    assert edit_review(client, review_id, comment="Only the text").status_code == 200
    review = Review.objects.get()
    assert (review.rating, review.comment) == (3, "Only the text")
    assert edit_review(client, review_id, rating=1).status_code == 200
    assert Review.objects.get().rating == 1 and Review.objects.get().comment == "Only the text"
    assert edit_review(client, review_id).status_code == 200  # nothing to change


def test_the_same_checks_as_writing_apply(shop):
    _, _, client, review_id = shop
    assert edit_review(client, review_id, rating=6).status_code == 400
    assert edit_review(client, review_id, rating="x").status_code == 400
    assert edit_review(client, review_id, comment="  ").status_code == 400
    assert edit_review(client, review_id, comment="x" * 2001).status_code == 400
    review = Review.objects.get()
    assert (review.rating, review.comment) == (3, "It is ok.")


def test_the_no_slash_spelling_works_too(shop):
    _, _, client, review_id = shop
    assert edit_review(client, review_id, url=f"{REVIEWS}{review_id}", rating=2).status_code == 200


def test_updated_at_moves_but_created_at_does_not(shop):
    _, _, client, review_id = shop
    before = Review.objects.get()
    edit_review(client, review_id, rating=4)
    after = Review.objects.get()
    assert after.created_at == before.created_at and after.updated_at > before.updated_at


def test_new_files_are_added_to_the_existing_ones(shop):
    _, _, client, review_id = shop
    edit_review(client, review_id, media=[image_upload("1.png")])

    response = edit_review(client, review_id, media=[video_upload(), image_upload("3.png")], rating=4)

    assert response.status_code == 200, response.content
    assert [item["type"] for item in data(response)["media_urls"]] == ["image/png", "video/mp4", "image/png"]
    assert ReviewMedia.objects.count() == 3


def test_the_five_file_limit_counts_the_files_already_there(shop):
    _, _, client, review_id = shop
    assert edit_review(client, review_id, media=[image_upload(f"{i}.png") for i in range(4)]).status_code == 200

    response = edit_review(client, review_id, media=[image_upload("a.png"), image_upload("b.png")], comment="More")

    assert response.status_code == 400
    assert response.json()["field_errors"]["media"] == ["A review can have at most 5 photos or videos."]
    assert ReviewMedia.objects.count() == 4 and Review.objects.get().comment == "It is ok."  # nothing changed at all
    assert edit_review(client, review_id, media=[image_upload("c.png")]).status_code == 200  # one more fits


def test_a_bad_new_file_changes_nothing(shop):
    _, _, client, review_id = shop
    response = edit_review(client, review_id, comment="Changed", media=[SimpleUploadedFile("x.png", b"nope")])
    assert response.status_code == 400
    assert Review.objects.get().comment == "It is ok."


def test_the_product_id_may_repeat_the_reviews_own_but_not_name_another(shop):
    product, _, client, review_id = shop
    other, _ = stocked("Plate")

    assert edit_review(client, review_id, product_id=product.pk, rating=4).status_code == 200
    response = edit_review(client, review_id, product_id=other.pk, rating=1)

    assert response.status_code == 400
    assert response.json()["field_errors"]["product_id"] == ["A review can not be moved to another product."]
    review = Review.objects.get()
    assert (review.product, review.rating) == (product, 4)


# --- who may edit ------------------------------------------------------------------------------------------------
def test_someone_elses_review_is_a_404_and_stays_untouched(shop):
    product, _, _, review_id = shop
    stranger = authed_client(other_customer(1))

    response = edit_review(stranger, review_id, rating=1, comment="Vandalised")

    assert response.status_code == 404 and response.json()["success"] is False
    review = Review.objects.get()
    assert (review.rating, review.comment) == (3, "It is ok.")


def test_a_guest_can_not_edit(shop, api_client):
    _, _, _, review_id = shop
    assert edit_review(api_client, review_id, rating=1).status_code == 401
    assert Review.objects.get().rating == 3


def test_an_unknown_review_is_a_404(shop):
    _, _, client, _ = shop
    assert edit_review(client, 999999, rating=1).status_code == 404


def test_a_review_the_staff_hid_is_a_404_for_its_author(shop):
    _, _, client, review_id = shop
    Review.objects.update(is_approved=False)
    assert edit_review(client, review_id, comment="Sneaky edit").status_code == 404
    assert Review.objects.get().comment == "It is ok."


def test_a_huge_review_id_is_a_404_not_a_server_error(shop):
    _, _, client, _ = shop
    assert edit_review(client, 10**30, rating=1).status_code == 404


def test_only_put_is_offered(shop):
    _, _, client, review_id = shop
    assert client.patch(f"{REVIEWS}{review_id}/", {"rating": 1}, format="multipart").status_code == 405
    assert client.delete(f"{REVIEWS}{review_id}/").status_code == 405
    assert Review.objects.count() == 1


def test_a_review_written_directly_is_editable_only_by_its_author():
    product, variant = stocked("Mug")
    user, client = buyer(product, variant)
    review = review_by(user, product, rating=2)
    stranger = authed_client(other_customer(2))
    assert edit_review(stranger, review.pk, rating=5).status_code == 404
    assert edit_review(client, review.pk, rating=5).status_code == 200
