"""The product's `total_reviews` and `avg_rating` always match its approved reviews, whatever changed them."""
from decimal import Decimal

import pytest

from apps.accounts.models import User
from apps.catalog.models import Product
from apps.reviews import services
from apps.reviews.models import Review
from apps.reviews.tests.helpers import (
    REVIEWS,
    buyer,
    data,
    edit_review,
    other_customer,
    review_by,
    reviewers,
    stocked,
    write_review,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def product():
    return stocked("Mug")[0]


def rating_of(product):
    product.refresh_from_db()
    return product.total_reviews, product.avg_rating


def test_a_product_without_reviews_has_no_rating(product):
    assert rating_of(product) == (0, Decimal("0.00"))


def test_the_rating_follows_reviews_written_through_the_api():
    product, variant = stocked("Mug")
    _, first = buyer(product, variant, "+8801711111111")
    _, second = buyer(product, variant, "+8801722222222")

    write_review(first, product, rating=5)
    assert rating_of(product) == (1, Decimal("5.00"))
    write_review(second, product, rating=2)
    assert rating_of(product) == (2, Decimal("3.50"))


def test_the_product_page_shows_the_new_numbers(api_client):
    product, variant = stocked("Mug")
    _, client = buyer(product, variant)
    write_review(client, product, rating=4)

    detail = data(api_client.get(f"/api/v1/products/detail/{product.slug}/"))

    assert detail["total_reviews"] == 1 and detail["avg_rating"] == 4


def test_editing_the_rating_recounts():
    product, variant = stocked("Mug")
    _, client = buyer(product, variant)
    review_id = data(write_review(client, product, rating=5))["id"]

    edit_review(client, review_id, rating=1)

    assert rating_of(product) == (1, Decimal("1.00"))


@pytest.mark.parametrize(
    "ratings, expected",
    [
        ([5, 4, 4], "4.33"),
        ([5, 4, 4, 4, 4, 4, 4, 4], "4.13"),  # 33 / 8 = 4.125: halves round UP (banker's rounding would say 4.12)
        ([1, 2], "1.50"),
        ([5, 5, 5, 5], "5.00"),
        ([1, 1, 1, 2], "1.25"),
        ([2, 2, 3], "2.33"),
        ([4, 5, 5], "4.67"),
    ],
)
def test_the_average_is_rounded_to_two_places_half_up(product, ratings, expected):
    reviewers(len(ratings), product, ratings)
    assert rating_of(product) == (len(ratings), Decimal(expected))


def test_hiding_a_review_takes_it_out_of_the_rating_and_showing_it_puts_it_back(product):
    reviewers(3, product, [5, 5, 2])
    assert rating_of(product) == (3, Decimal("4.00"))
    low = Review.objects.get(rating=2)

    low.is_approved = False
    low.save()
    assert rating_of(product) == (2, Decimal("5.00"))

    low.is_approved = True
    low.save()
    assert rating_of(product) == (3, Decimal("4.00"))


def test_deleting_a_review_recounts(product):
    reviewers(3, product, [5, 5, 2])
    Review.objects.get(rating=2).delete()
    assert rating_of(product) == (2, Decimal("5.00"))


def test_deleting_the_last_review_goes_back_to_zero(product):
    reviewers(1, product, [4])
    Review.objects.all().delete()
    assert rating_of(product) == (0, Decimal("0.00"))


def test_deleting_many_reviews_at_once_recounts_every_product():
    mug, plate = stocked("Mug")[0], stocked("Plate")[0]
    reviewers(3, mug, [5, 5, 5])
    review_by(other_customer(1), plate, 1)
    review_by(other_customer(2), plate, 3)

    Review.objects.filter(rating__gte=3).delete()

    assert rating_of(mug) == (0, Decimal("0.00"))
    assert rating_of(plate) == (1, Decimal("1.00"))


def test_a_customer_who_leaves_takes_their_reviews_out_of_the_rating(product):
    users = reviewers(3, product, [5, 5, 2])
    User.objects.get(pk=users[2].pk).delete()  # the 2-star reviewer
    assert rating_of(product) == (2, Decimal("5.00"))


def test_reviews_of_different_products_do_not_mix():
    mug, plate = stocked("Mug")[0], stocked("Plate")[0]
    review_by(other_customer(1), mug, 5)
    review_by(other_customer(2), plate, 1)
    assert rating_of(mug) == (1, Decimal("5.00")) and rating_of(plate) == (1, Decimal("1.00"))


def test_recounting_repairs_a_wrong_number(product):
    reviewers(2, product, [4, 5])
    Product.objects.filter(pk=product.pk).update(total_reviews=99, avg_rating=Decimal("1.00"))

    services.refresh_product_rating(product.pk)

    assert rating_of(product) == (2, Decimal("4.50"))


def test_recounting_a_product_that_is_gone_does_nothing():
    services.refresh_product_rating(999999)  # no error


def test_the_other_counters_are_left_alone(product):
    Product.objects.filter(pk=product.pk).update(total_orders=7, total_views=11)
    reviewers(1, product, [5])
    product.refresh_from_db()
    assert (product.total_orders, product.total_views) == (7, 11)


def test_the_rating_of_a_hidden_product_is_still_kept(product):
    reviewers(1, product, [3])
    Product.objects.filter(pk=product.pk).update(is_active=False)
    services.refresh_product_rating(product.pk)
    assert rating_of(product) == (1, Decimal("3.00"))


def test_the_review_list_and_the_product_agree(api_client):
    product, variant = stocked("Mug")
    reviewers(4, product, [5, 4, 4, 3])
    listed = data(api_client.get(REVIEWS, {"product_id": product.pk}))
    assert listed["count"] == rating_of(product)[0]
