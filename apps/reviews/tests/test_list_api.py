"""GET /products/reviews/?product_id=: public, newest first, with can_review / can_edited for the signed-in customer."""
import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.models import User
from apps.catalog.models import Product
from apps.reviews.models import Review, ReviewMedia
from apps.reviews.tests.helpers import (
    REVIEWS,
    authed_client,
    buyer,
    data,
    image_upload,
    other_customer,
    review_by,
    reviewers,
    stocked,
    write_review,
)

pytestmark = pytest.mark.django_db


def fetch(client, product, **params):
    return client.get(REVIEWS, {"product_id": product.pk, **params})


@pytest.fixture
def product():
    return stocked("Mug")[0]


def test_a_guest_sees_the_reviews(api_client, product):
    users = reviewers(2, product, [5, 3])

    response = fetch(api_client, product)

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["success"] is True
    assert set(body["data"]) == {"count", "next", "previous", "results", "can_review"}
    assert body["data"]["count"] == 2 and body["data"]["can_review"] is False
    first = body["data"]["results"][0]
    assert set(first) == {"id", "product_id", "user_name", "rating", "comment", "created_at", "can_edited", "media_urls"}
    assert first["can_edited"] is False
    assert {item["user_name"] for item in body["data"]["results"]} == {user.name for user in users}


def test_newest_first(api_client, product):
    reviewers(3, product, [5, 4, 3])
    assert [item["rating"] for item in data(fetch(api_client, product))["results"]] == [3, 4, 5]


def test_only_this_products_reviews(api_client, product):
    other, _ = stocked("Plate")
    reviewers(1, product, [5])
    review_by(other_customer(5), other, 1, "Plate review")
    assert [item["comment"] for item in data(fetch(api_client, other))["results"]] == ["Plate review"]


def test_a_product_without_reviews_has_an_empty_list(api_client, product):
    body = data(fetch(api_client, product))
    assert body["count"] == 0 and body["results"] == [] and body["can_review"] is False


def test_hidden_reviews_are_not_listed(api_client, product):
    reviewers(3, product, [5, 4, 3])
    Review.objects.filter(rating=4).update(is_approved=False)
    body = data(fetch(api_client, product))
    assert body["count"] == 2 and sorted(item["rating"] for item in body["results"]) == [3, 5]


def test_the_author_sees_can_edited_on_their_own_review_only():
    product, variant = stocked("Mug")
    user, client = buyer(product, variant)
    write_review(client, product, comment="Mine")
    review_by(other_customer(3), product, 2, "Theirs")

    results = data(fetch(client, product))["results"]

    assert {item["comment"]: item["can_edited"] for item in results} == {"Mine": True, "Theirs": False}
    guest_view = data(fetch(authed_client(other_customer(4)), product))["results"]
    assert {item["can_edited"] for item in guest_view} == {False}


def test_the_media_of_a_review_are_listed_with_absolute_urls(api_client):
    product, variant = stocked("Mug")
    _, client = buyer(product, variant)
    write_review(client, product, media=[image_upload()])

    item = data(fetch(api_client, product))["results"][0]

    assert item["media_urls"][0]["file"].startswith("http://testserver/media/reviews/")
    assert item["media_urls"][0]["type"] == "image/png"


def test_no_contact_details_are_ever_shown(api_client, product):
    users = reviewers(2, product, [5, 5])
    text = fetch(api_client, product).content.decode()
    for user in users:
        assert user.phone_number not in text


def test_a_user_without_a_name_shows_as_customer(api_client, product):
    (user,) = reviewers(1, product, [5])
    User.objects.filter(pk=user.pk).update(name="")
    assert data(fetch(api_client, product))["results"][0]["user_name"] == "Customer"


# --- query parameters ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("params", [{}, {"product_id": ""}, {"product_id": "abc"}, {"product_id": 0}, {"product_id": -2}])
def test_the_product_id_is_required_and_must_be_a_positive_number(api_client, params):
    response = api_client.get(REVIEWS, params)
    assert response.status_code == 400
    assert "product_id" in response.json()["field_errors"]


def test_an_unknown_product_is_a_404(api_client):
    response = api_client.get(REVIEWS, {"product_id": 999999})
    assert response.status_code == 404 and response.json()["success"] is False


def test_a_hidden_product_is_a_404(api_client, product):
    reviewers(1, product, [5])
    Product.objects.filter(pk=product.pk).update(is_active=False)
    assert fetch(api_client, product).status_code == 404


def test_the_no_slash_spelling_works_too(api_client, product):
    assert api_client.get(REVIEWS.rstrip("/"), {"product_id": product.pk}).status_code == 200


# --- pagination ------------------------------------------------------------------------------------------------
def test_reviews_come_in_pages(api_client, product):
    reviewers(5, product, [1, 2, 3, 4, 5])

    first = data(fetch(api_client, product, page_size=2))
    assert first["count"] == 5 and [item["rating"] for item in first["results"]] == [5, 4]
    assert first["next"] is not None and first["previous"] is None and first["can_review"] is False

    last = data(fetch(api_client, product, page_size=2, page=3))
    assert [item["rating"] for item in last["results"]] == [1] and last["next"] is None


def test_a_page_past_the_end_is_empty_not_an_error(api_client, product):
    reviewers(3, product, [5, 5, 5])
    body = data(fetch(api_client, product, page_size=2, page=9))
    assert body["results"] == [] and body["count"] == 3 and body["can_review"] is False


def test_can_review_is_also_on_later_pages():
    product, variant = stocked("Mug")
    _, client = buyer(product, variant)
    reviewers(3, product, [5, 5, 5])
    assert data(fetch(client, product, page_size=2, page=2))["can_review"] is True
    assert data(fetch(client, product, page_size=2, page=9))["can_review"] is True


# --- tokens and speed --------------------------------------------------------------------------------------------
def test_an_expired_token_is_a_401_like_everywhere_else(product):
    """A public page does not quietly ignore a bad token: the frontend refreshes it like everywhere else."""
    user = other_customer(7)
    token = AccessToken.for_user(user)
    token.set_exp(from_time=timezone.now() - timedelta(days=1), lifetime=timedelta(seconds=1))
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    assert fetch(client, product).status_code == 401


def test_the_number_of_queries_does_not_grow_with_the_reviews(api_client, product):
    def add_reviews(count, start):
        for index in range(start, start + count):
            user = User.objects.create_user(f"+88019000{index:05d}", name=f"Customer {index}")
            ReviewMedia.objects.create(review=review_by(user, product, 3), file=image_upload())

    def queries():
        with CaptureQueriesContext(connection) as captured:
            assert fetch(api_client, product).status_code == 200
        return len(captured)

    add_reviews(2, start=0)
    few = queries()
    add_reviews(10, start=2)
    many = queries()

    assert many == few, f"{few} queries for 2 reviews, {many} for 12"
