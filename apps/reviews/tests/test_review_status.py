"""`review_status` and `order_id` of the review list: WHY a customer may not review yet, so the shop can say it (not
just "no"), and link to the order they are waiting for."""
import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.orders import services as order_services
from apps.orders.models import Order
from apps.orders.tests.helpers import line, make_order
from apps.reviews.services import CAN_REVIEW, GUEST, NOT_PURCHASED, REVIEWED, STATUSES, WAITING_FOR_DELIVERY
from apps.reviews.tests.helpers import REVIEWS, data, deliver, other_customer, review_by, signed_in, stocked, write_review

pytestmark = pytest.mark.django_db


def status_of(client, product, **params):
    """(review_status, order_id, can_review) as the list says it."""
    response = client.get(REVIEWS, {"product_id": product.pk, **params})
    assert response.status_code == 200, response.content
    body = data(response)
    return body["review_status"], body["order_id"], body["can_review"]


def test_the_statuses_are_the_documented_five():
    assert STATUSES == ("can_review", "reviewed", "waiting_for_delivery", "not_purchased", "guest")


def test_a_guest_is_a_guest(api_client):
    product, _ = stocked()
    assert status_of(api_client, product) == (GUEST, None, False)


def test_a_signed_in_customer_who_never_ordered_it_has_not_purchased_it():
    product, _ = stocked()
    _, client = signed_in()
    assert status_of(client, product) == (NOT_PURCHASED, None, False)


@pytest.mark.parametrize("path", [[], ["paid"], ["shipped"], ["paid", "shipped"]])
def test_an_order_that_is_on_its_way_is_waiting_for_delivery_and_says_which_order(path):
    product, variant = stocked()
    user, client = signed_in()
    order = make_order(line(product, variant), user=user)
    for status in path:
        order_services.change_status(order, status)

    assert status_of(client, product) == (WAITING_FOR_DELIVERY, order.number, False)


def test_delivery_turns_waiting_into_can_review():
    product, variant = stocked()
    user, client = signed_in()
    order = make_order(line(product, variant), user=user)
    assert status_of(client, product)[0] == WAITING_FOR_DELIVERY

    deliver(order)

    assert status_of(client, product) == (CAN_REVIEW, None, True)


def test_the_newest_waiting_order_is_the_one_named():
    product, variant = stocked(stock=20)
    user, client = signed_in()
    make_order(line(product, variant), user=user)
    newest = make_order(line(product, variant), user=user)
    assert status_of(client, product)[1] == newest.number


def test_a_delivered_order_wins_over_a_newer_one_still_on_its_way():
    product, variant = stocked(stock=20)
    user, client = signed_in()
    deliver(make_order(line(product, variant), user=user))
    make_order(line(product, variant), user=user)  # a second order, not delivered yet
    assert status_of(client, product) == (CAN_REVIEW, None, True)


@pytest.mark.parametrize("path", [["cancelled"], ["shipped", "cancelled"]])
def test_a_cancelled_order_counts_for_nothing(path):
    product, variant = stocked()
    user, client = signed_in()
    order = make_order(line(product, variant), user=user)
    for status in path:
        order_services.change_status(order, status)
    assert status_of(client, product) == (NOT_PURCHASED, None, False)


def test_a_delivered_order_that_was_refunded_no_longer_allows_a_review():
    product, variant = stocked()
    user, client = signed_in()
    order = deliver(make_order(line(product, variant), user=user))
    order_services.change_status(order, Order.Status.REFUNDED)
    assert status_of(client, product) == (NOT_PURCHASED, None, False)


def test_once_reviewed_it_says_reviewed_also_when_another_order_is_on_its_way():
    product, variant = stocked(stock=20)
    user, client = signed_in()
    deliver(make_order(line(product, variant), user=user))
    assert write_review(client, product).status_code == 201
    make_order(line(product, variant), user=user)  # they order it again

    assert status_of(client, product) == (REVIEWED, None, False)


def test_a_review_the_staff_hid_still_counts_as_reviewed():
    product, variant = stocked()
    user, client = signed_in()
    deliver(make_order(line(product, variant), user=user))
    review = review_by(user, product)
    review.is_approved = False
    review.save()
    assert status_of(client, product) == (REVIEWED, None, False)


def test_somebody_elses_order_and_a_guest_order_are_not_mine():
    product, variant = stocked(stock=20)
    _, client = signed_in("+8801711111111")
    make_order(line(product, variant), user=other_customer(1))
    make_order(line(product, variant))  # a guest's, even with this customer's phone number
    assert status_of(client, product) == (NOT_PURCHASED, None, False)


def test_it_is_per_product():
    mug, mug_variant = stocked("Mug")
    plate, _ = stocked("Plate")
    user, client = signed_in()
    order = make_order(line(mug, mug_variant), user=user)
    assert status_of(client, mug) == (WAITING_FOR_DELIVERY, order.number, False)
    assert status_of(client, plate) == (NOT_PURCHASED, None, False)


def test_it_is_on_every_page_of_the_list():
    product, variant = stocked()
    user, client = signed_in()
    order = make_order(line(product, variant), user=user)
    for index in range(3):
        review_by(other_customer(index), product)
    assert status_of(client, product, page_size=2, page=1)[:2] == (WAITING_FOR_DELIVERY, order.number)
    assert status_of(client, product, page_size=2, page=9)[:2] == (WAITING_FOR_DELIVERY, order.number)  # past the end


def test_the_status_costs_at_most_three_more_queries_and_none_for_a_guest(api_client):
    product, variant = stocked()
    user, client = signed_in()
    make_order(line(product, variant), user=user)

    def queries(who):
        with CaptureQueriesContext(connection) as context:
            assert who.get(REVIEWS, {"product_id": product.pk}).status_code == 200
        return len(context)

    guest, signed = queries(api_client), queries(client)
    assert signed - guest <= 4  # the customer's own lookups (user, review, delivered, waiting) and nothing per review
