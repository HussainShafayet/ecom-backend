"""Who may review a product: a customer with a DELIVERED order that contains it, once."""
import pytest

from apps.orders import services as order_services
from apps.orders.models import Order
from apps.orders.tests.helpers import line, make_order
from apps.reviews.models import Review
from apps.reviews.tests.helpers import (
    REVIEWS,
    buyer,
    data,
    delivered_order,
    deliver,
    signed_in,
    stocked,
    write_review,
)

pytestmark = pytest.mark.django_db
NOT_DELIVERED = "You can review a product once an order that contains it has been delivered."


def errors_of(response):
    assert response.status_code == 400, response.content
    return response.json()["errors"]


def test_a_customer_with_a_delivered_order_can_review_the_product():
    product, variant = stocked()
    user, client = buyer(product, variant)

    response = write_review(client, product, rating=4, comment="Nice mug.")

    assert response.status_code == 201, response.content
    review = Review.objects.get()
    assert (review.user, review.product, review.rating, review.comment) == (user, product, 4, "Nice mug.")


def test_the_review_records_the_purchase_that_made_it_possible():
    product, variant = stocked()
    user, client = signed_in()
    delivered_order(user, product, variant)
    latest = delivered_order(user, product, variant)  # a later delivered order

    write_review(client, product)

    assert Review.objects.get().order_item == latest.items.get()


@pytest.mark.parametrize(
    "path",
    [
        [],  # placed, never moved
        [Order.Status.SHIPPED],
        [Order.Status.PAID],
        [Order.Status.CANCELLED],
        [Order.Status.PAID, Order.Status.REFUNDED],
    ],
    ids=["pending", "shipped", "paid", "cancelled", "refunded-before-shipping"],
)
def test_an_order_that_was_not_delivered_does_not_count(path):
    product, variant = stocked()
    user, client = signed_in()
    order = make_order(line(product, variant), user=user)
    for status in path:
        order_services.change_status(order, status)

    response = write_review(client, product)

    assert errors_of(response) == [NOT_DELIVERED]
    assert Review.objects.count() == 0


def test_a_delivered_order_that_was_refunded_afterwards_no_longer_counts():
    product, variant = stocked()
    user, client = signed_in()
    order = delivered_order(user, product, variant)
    order_services.change_status(order, Order.Status.REFUNDED)

    assert errors_of(write_review(client, product)) == [NOT_DELIVERED]


def test_a_customer_without_any_order_is_refused():
    product, _ = stocked()
    _, client = signed_in()
    assert errors_of(write_review(client, product)) == [NOT_DELIVERED]


def test_another_customers_delivered_order_does_not_count():
    product, variant = stocked(stock=10)
    buyer(product, variant, phone="+8801711111111")
    _, stranger = signed_in("+8801722222222")

    assert errors_of(write_review(stranger, product)) == [NOT_DELIVERED]


def test_a_guest_order_is_never_attached_to_an_account():
    """Guest orders have no user, not even when the phone number is the same as an account's."""
    product, variant = stocked()
    user, client = signed_in()
    deliver(make_order(line(product, variant), user=None, phone_number=user.phone_number))

    assert errors_of(write_review(client, product)) == [NOT_DELIVERED]


def test_a_delivered_order_of_another_product_does_not_count():
    bought, variant = stocked("Mug")
    other, _ = stocked("Plate")
    _, client = buyer(bought, variant)

    assert errors_of(write_review(client, other)) == [NOT_DELIVERED]
    assert write_review(client, bought).status_code == 201


def test_a_second_review_of_the_same_product_is_refused():
    product, variant = stocked()
    _, client = buyer(product, variant)
    assert write_review(client, product).status_code == 201

    response = write_review(client, product, comment="Again!")

    assert errors_of(response) == ["You have already reviewed this product. Edit your review instead."]
    assert Review.objects.count() == 1


def test_a_second_delivered_order_does_not_allow_a_second_review():
    product, variant = stocked(stock=10)
    user, client = buyer(product, variant)
    write_review(client, product)
    delivered_order(user, product, variant)

    assert write_review(client, product).status_code == 400
    assert Review.objects.count() == 1


def test_a_review_stays_when_its_order_is_refunded_later():
    product, variant = stocked()
    user, client = signed_in()
    order = delivered_order(user, product, variant)
    write_review(client, product)

    order_services.change_status(order, Order.Status.REFUNDED)

    assert Review.objects.count() == 1


def test_a_guest_can_not_write_a_review(api_client):
    product, _ = stocked()
    response = write_review(api_client, product)
    assert response.status_code == 401
    assert response.json()["success"] is False


# --- can_review in the list --------------------------------------------------------------------------------------
def can_review(client, product):
    response = client.get(REVIEWS, {"product_id": product.pk})
    assert response.status_code == 200, response.content
    return data(response)["can_review"]


def test_can_review_follows_the_order_and_the_review(api_client):
    product, variant = stocked()
    user, client = signed_in()
    assert can_review(api_client, product) is False  # a guest never can
    assert can_review(client, product) is False  # no order yet

    order = make_order(line(product, variant), user=user)
    assert can_review(client, product) is False  # ordered, not delivered

    deliver(order)
    assert can_review(client, product) is True

    write_review(client, product)
    assert can_review(client, product) is False  # once only


def test_can_review_is_per_product():
    mug, mug_variant = stocked("Mug")
    plate, _ = stocked("Plate")
    _, client = buyer(mug, mug_variant)

    assert can_review(client, mug) is True
    assert can_review(client, plate) is False
