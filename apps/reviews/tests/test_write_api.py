"""POST /products/reviews/: what the review form sends, what comes back, and what is refused."""
import pytest

from apps.catalog.models import Product
from apps.reviews.models import Review
from apps.reviews.tests.helpers import REVIEWS, buyer, data, stocked, write_review

pytestmark = pytest.mark.django_db


@pytest.fixture
def shop():
    product, variant = stocked("Mug")
    user, client = buyer(product, variant)
    return product, user, client


def test_the_created_review_has_the_shape_the_frontend_reads(shop):
    product, user, client = shop

    response = write_review(client, product, rating=4, comment="Nice mug.")

    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True and body["message"] == "Review added."
    review = Review.objects.get()
    assert set(body["data"]) == {
        "id",
        "product_id",
        "user_name",
        "rating",
        "comment",
        "created_at",
        "can_edited",
        "media_urls",
    }
    assert body["data"] | {"created_at": None} == {
        "id": review.pk,
        "product_id": product.pk,
        "user_name": "Rahim",
        "rating": 4,
        "comment": "Nice mug.",
        "created_at": None,
        "can_edited": True,
        "media_urls": [],
    }
    assert body["data"]["created_at"].startswith(review.created_at.strftime("%Y-%m-%dT"))


def test_the_comment_is_trimmed(shop):
    product, _, client = shop
    write_review(client, product, comment="   Good value.  \n")
    assert Review.objects.get().comment == "Good value."


def test_a_json_body_works_too(shop):
    product, _, client = shop
    response = client.post(REVIEWS, {"product_id": product.pk, "rating": 5, "comment": "Great"}, format="json")
    assert response.status_code == 201


def test_the_no_slash_spelling_works_too(shop):
    product, _, client = shop
    response = client.post(
        REVIEWS.rstrip("/"), {"product_id": product.pk, "rating": 5, "comment": "Great"}, format="multipart"
    )
    assert response.status_code == 201


def test_the_name_shown_is_the_customers_name_never_their_phone(shop):
    product, user, client = shop
    user.name = "  "
    user.save()
    body = write_review(client, product).json()
    assert body["data"]["user_name"] == "Customer"
    assert user.phone_number not in str(body)


@pytest.mark.parametrize("rating", [0, 6, -1, 4.5, "abc", ""])
def test_the_rating_must_be_a_whole_number_from_1_to_5(shop, rating):
    product, _, client = shop
    response = write_review(client, product, rating=rating)
    assert response.status_code == 400
    assert "rating" in response.json()["field_errors"]
    assert Review.objects.count() == 0


def test_the_rating_is_required(shop):
    product, _, client = shop
    response = client.post(REVIEWS, {"product_id": product.pk, "comment": "x"}, format="multipart")
    assert response.status_code == 400 and "rating" in response.json()["field_errors"]


@pytest.mark.parametrize("comment", ["", "   ", "\n\t "])
def test_the_comment_may_not_be_empty(shop, comment):
    product, _, client = shop
    response = write_review(client, product, comment=comment)
    assert response.status_code == 400 and "comment" in response.json()["field_errors"]


def test_the_comment_has_a_length_limit(shop):
    product, _, client = shop
    assert write_review(client, product, comment="x" * 2001).status_code == 400
    assert write_review(client, product, comment="x" * 2000).status_code == 201


@pytest.mark.parametrize("value", [None, "", "abc", 0, -3])
def test_the_product_id_must_be_a_positive_number(shop, value):
    _, _, client = shop
    body = {"rating": 5, "comment": "Fine"}
    if value is not None:
        body["product_id"] = value
    response = client.post(REVIEWS, body, format="multipart")
    assert response.status_code == 400 and "product_id" in response.json()["field_errors"]


def test_an_unknown_product_is_refused(shop):
    _, _, client = shop
    response = client.post(REVIEWS, {"product_id": 999999, "rating": 5, "comment": "x"}, format="multipart")
    assert response.status_code == 400
    assert response.json()["field_errors"]["product_id"] == ["This product is not available."]


def test_a_hidden_product_can_not_be_reviewed(shop):
    product, _, client = shop
    Product.objects.filter(pk=product.pk).update(is_active=False)
    response = write_review(client, product)
    assert response.status_code == 400 and "product_id" in response.json()["field_errors"]
    assert Review.objects.count() == 0


def test_a_body_that_is_not_an_object_is_a_400_not_a_500(shop):
    _, _, client = shop
    assert client.post(REVIEWS, [1, 2], format="json").status_code == 400


def test_a_new_review_is_shown_at_once(shop):
    product, _, client = shop
    write_review(client, product, comment="Visible")
    assert Review.objects.get().is_approved is True
    listed = data(client.get(REVIEWS, {"product_id": product.pk}))["results"]
    assert [item["comment"] for item in listed] == ["Visible"]


def test_a_review_of_the_product_is_counted_on_it(shop):
    product, _, client = shop
    write_review(client, product, rating=4)
    product.refresh_from_db()
    assert (product.total_reviews, str(product.avg_rating)) == (1, "4.00")


def test_a_null_character_in_the_comment_is_a_400_not_a_database_error(shop):
    product, _, client = shop
    response = write_review(client, product, comment="bad\x00text")
    assert response.status_code == 400 and "comment" in response.json()["field_errors"]


def test_a_huge_product_id_is_refused_cleanly(shop):
    _, _, client = shop
    body = {"product_id": 10**30, "rating": 5, "comment": "x"}
    assert client.post(REVIEWS, body, format="multipart").status_code == 400
    assert client.get(REVIEWS, {"product_id": 10**30}).status_code == 404


def test_emoji_and_bengali_text_survive(shop):
    product, _, client = shop
    text = "দারুণ মগ 👍 — worth it"
    assert data(write_review(client, product, comment=text))["comment"] == text
