"""GET /products/reviews/featured/: what customers say, for the homepage. The reviews the staff ticked, else the shop's pick."""
from types import SimpleNamespace

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.orders.models import OrderItem
from apps.reviews import services
from apps.reviews.models import ReviewMedia
from apps.reviews.tests.helpers import data, delivered_order, image_upload, other_customer, review_by, stocked, video_upload

pytestmark = pytest.mark.django_db

URL = "/api/v1/products/reviews/featured/"
GOOD = "Really good quality, it arrived on time and works well."  # 55 characters: a comment worth showing


@pytest.fixture
def shelf():
    """A product with plenty of stock: (product, variant)."""
    return stocked("Mug", stock=200)


def fetch(client):
    response = client.get(URL)
    assert response.status_code == 200, response.content
    return data(response)["reviews"]


def ids(reviews):
    return [review["id"] for review in reviews]


def customer(number, name="Rahim Uddin"):
    user = other_customer(number)
    user.name = name
    user.save(update_fields=["name"])
    return user


def verified(number, shelf, rating=5, comment=GOOD, name="Rahim Uddin", **extra):
    """A review that came from a delivered purchase (what the API creates)."""
    product, variant = shelf
    user = customer(number, name)
    order = delivered_order(user, product, variant)
    return review_by(user, product, rating, comment, order_item=OrderItem.objects.get(order=order), **extra)


def unverified(number, shelf, rating=5, comment=GOOD, name="Rahim Uddin", **extra):
    return review_by(customer(number, name), shelf[0], rating, comment, **extra)


# --- the answer ---------------------------------------------------------------------------------------------------
def test_a_guest_gets_the_envelope_and_an_empty_list_when_there_is_nothing(api_client):
    response = api_client.get(URL)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True and body["data"] == {"reviews": []}


def test_a_stale_token_is_not_a_401(api_client, shelf):
    unverified(1, shelf, show_on_homepage=True)

    response = api_client.get(URL, HTTP_AUTHORIZATION="Bearer not-a-real-token")

    assert response.status_code == 200
    assert len(data(response)["reviews"]) == 1


def test_a_review_carries_what_the_homepage_draws(api_client, shelf):
    review = verified(1, shelf, rating=4, comment=GOOD, show_on_homepage=True)

    [item] = fetch(api_client)

    assert set(item) == {"id", "reviewer", "rating", "comment", "created_at", "verified", "product_name", "product_slug", "image"}
    assert item["id"] == review.pk and item["rating"] == 4 and item["comment"] == GOOD
    assert (item["reviewer"], item["verified"]) == ("Rahim U.", True)
    assert (item["product_name"], item["product_slug"]) == ("Mug", shelf[0].slug)
    assert item["image"] is None


def test_a_review_that_is_not_from_a_purchase_is_not_called_verified(api_client, shelf):
    unverified(1, shelf, show_on_homepage=True)

    assert fetch(api_client)[0]["verified"] is False


def test_it_never_gives_away_a_phone_number_or_an_e_mail(api_client, shelf):
    user = customer(1)
    user.email = "rahim.secret@example.com"
    user.save(update_fields=["email"])
    review_by(user, shelf[0], 5, GOOD, show_on_homepage=True)

    body = api_client.get(URL).content.decode()

    assert user.phone_number not in body and "rahim.secret" not in body and "Uddin" not in body


def test_the_first_photo_is_the_image_and_a_video_is_not(api_client, shelf):
    with_photo = review_by(customer(1), shelf[0], 5, GOOD, show_on_homepage=True)
    ReviewMedia.objects.create(review=with_photo, file=video_upload())
    ReviewMedia.objects.create(review=with_photo, file=image_upload())
    only_video = review_by(customer(2), shelf[0], 5, GOOD, show_on_homepage=True)
    ReviewMedia.objects.create(review=only_video, file=video_upload())

    by_id = {item["id"]: item for item in fetch(api_client)}

    assert by_id[with_photo.pk]["image"].startswith("http") and by_id[with_photo.pk]["image"].endswith((".png", ".jpg", ".webp"))
    assert by_id[only_video.pk]["image"] is None


def test_a_page_of_reviews_costs_the_same_queries_however_many(api_client, shelf):
    def queries():
        with CaptureQueriesContext(connection) as context:
            api_client.get(URL)
        return len(context)

    for number in range(1, 3):
        ReviewMedia.objects.create(review=review_by(customer(number), shelf[0], 5, GOOD, show_on_homepage=True), file=image_upload())
    few = queries()
    for number in range(3, 8):
        ReviewMedia.objects.create(review=review_by(customer(number), shelf[0], 5, GOOD, show_on_homepage=True), file=image_upload())

    assert queries() == few


# --- how the reviewer is named --------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "name, shown",
    [
        ("Rahim Uddin", "Rahim U."),
        ("Rahim", "Rahim"),
        ("", "Customer"),
        ("   ", "Customer"),
        ("  Rahim   Ahmed  Khan ", "Rahim K."),
        ("rahim uddin", "rahim U."),
        ("রহিম উদ্দিন", "রহিম উ."),
        ("A" * 80 + " Zaman", "A" * 30 + " Z."),
    ],
)
def test_the_name_is_the_first_name_and_the_initial_of_the_last(name, shown):
    assert services.short_name(SimpleNamespace(name=name)) == shown


# --- the ones the staff ticked ----------------------------------------------------------------------------------------
def test_when_the_staff_ticked_some_only_those_are_shown(api_client, shelf):
    ticked = unverified(1, shelf, 3, "ok", show_on_homepage=True)  # the staff decide: a short, 3-star one is fine
    verified(2, shelf)  # a good one nobody ticked

    assert ids(fetch(api_client)) == [ticked.pk]


def test_the_ticked_ones_come_newest_first(api_client, shelf):
    first = unverified(1, shelf, show_on_homepage=True)
    second = unverified(2, shelf, show_on_homepage=True)
    third = unverified(3, shelf, show_on_homepage=True)

    assert ids(fetch(api_client)) == [third.pk, second.pk, first.pk]


def test_at_most_eight_are_shown(api_client, shelf):
    made = [unverified(number, shelf, show_on_homepage=True) for number in range(1, 12)]

    assert ids(fetch(api_client)) == [review.pk for review in reversed(made)][:8]


def test_a_ticked_review_the_staff_hid_is_not_shown(api_client, shelf):
    hidden = unverified(1, shelf, show_on_homepage=True, is_approved=False)
    shown = unverified(2, shelf, show_on_homepage=True)

    assert ids(fetch(api_client)) == [shown.pk]
    assert hidden.pk not in ids(fetch(api_client))


def test_a_ticked_review_of_a_hidden_product_is_not_shown(api_client, shelf):
    hidden_product, _ = stocked("Old Mug", is_active=False)
    review_by(customer(1), hidden_product, 5, GOOD, show_on_homepage=True)
    shown = unverified(2, shelf, show_on_homepage=True)

    assert ids(fetch(api_client)) == [shown.pk]


def test_when_none_of_the_ticked_ones_can_be_shown_the_shop_picks(api_client, shelf):
    unverified(1, shelf, show_on_homepage=True, is_approved=False)
    good = verified(2, shelf)

    assert ids(fetch(api_client)) == [good.pk]


# --- the shop's pick (nothing ticked) ---------------------------------------------------------------------------------
def test_the_shop_picks_good_reviews_from_real_purchases(api_client, shelf):
    good = verified(1, shelf, 5)
    also_good = verified(2, shelf, 4)

    assert set(ids(fetch(api_client))) == {good.pk, also_good.pk}


def test_a_low_rating_a_short_comment_or_no_purchase_is_not_picked(api_client, shelf):
    verified(1, shelf, 3)  # 3 stars
    verified(2, shelf, 5, "Nice.")  # says nothing
    unverified(3, shelf, 5)  # not from a delivered purchase
    verified(4, shelf, 5, is_approved=False)  # hidden by the staff
    old_product, old_variant = stocked("Old Mug", stock=5)
    review_by(customer(5), old_product, 5, GOOD, order_item=OrderItem.objects.get(order=delivered_order(customer(6), old_product, old_variant)))
    old_product.is_active = False  # taken off the shop after it was bought
    old_product.save()

    assert fetch(api_client) == []


def test_a_comment_of_forty_characters_is_long_enough_and_thirty_nine_is_not(api_client, shelf):
    enough = verified(1, shelf, 5, "x" * 40)
    verified(2, shelf, 5, "x" * 39)

    assert ids(fetch(api_client)) == [enough.pk]


def test_the_best_rating_comes_first_then_the_newest(api_client, shelf):
    four_old = verified(1, shelf, 4)
    five_old = verified(2, shelf, 5)
    five_new = verified(3, shelf, 5)
    four_new = verified(4, shelf, 4)

    assert ids(fetch(api_client)) == [five_new.pk, five_old.pk, four_new.pk, four_old.pk]


def test_one_review_per_customer(api_client, shelf):
    product, variant = shelf
    other, other_variant = stocked("Kettle", stock=50)
    user = customer(1)
    item = OrderItem.objects.get(order=delivered_order(user, product, variant))
    other_item = OrderItem.objects.get(order=delivered_order(user, other, other_variant))
    best = review_by(user, product, 5, GOOD, order_item=item)
    review_by(user, other, 4, GOOD, order_item=other_item)

    assert ids(fetch(api_client)) == [best.pk]


def test_at_most_eight_are_picked(api_client, shelf):
    made = [verified(number, shelf, 5) for number in range(1, 12)]

    got = ids(fetch(api_client))

    assert len(got) == 8 and got == [review.pk for review in reversed(made)][:8]


def test_a_customer_with_many_reviews_does_not_use_up_the_places(api_client, shelf):
    product, variant = shelf
    user = customer(1)
    for index in range(12):  # one customer, twelve five-star reviews of twelve products
        other, other_variant = stocked(f"Mug {index}", stock=5)
        review_by(user, other, 5, GOOD, order_item=OrderItem.objects.get(order=delivered_order(user, other, other_variant)))
    crowd = [verified(number, shelf, 4) for number in range(2, 9)]

    got = ids(fetch(api_client))

    assert len(got) == 8 and set(got[1:]) == {review.pk for review in crowd}


def test_the_ticked_ones_win_over_the_shops_pick(api_client, shelf):
    verified(1, shelf, 5)
    ticked = unverified(2, shelf, 4, "fine", show_on_homepage=True)

    assert ids(fetch(api_client)) == [ticked.pk]
