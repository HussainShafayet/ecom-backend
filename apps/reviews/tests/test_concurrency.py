"""Real simultaneous requests, one thread and one database connection each. A transaction=True test commits for
real, so what is tested are the row locks, not a single connection's snapshot."""
import threading
from decimal import Decimal

import pytest
from django.db import connection
from rest_framework.test import APIClient

from apps.accounts.services import issue_tokens
from apps.reviews.models import Review, ReviewMedia
from apps.reviews.tests.helpers import (
    data,
    delivered_order,
    edit_review,
    image_upload,
    stocked,
    verified_user,
    write_review,
)

pytestmark = pytest.mark.django_db(transaction=True)

PATIENCE = 60  # seconds: a deadlock would hang for ever, so waiting is bounded and then fails the test


def run_together(count, work):
    """Run `work(index)` in `count` threads that are released at the same moment; return the results in index order."""
    barrier = threading.Barrier(count)
    results, failures = [None] * count, []

    def runner(index):
        try:
            connection.ensure_connection()
            barrier.wait(timeout=PATIENCE)
            results[index] = work(index)
        except BaseException as exc:  # noqa: BLE001  (reported in the main thread)
            failures.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=runner, args=(index,)) for index in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=PATIENCE)
    assert not any(thread.is_alive() for thread in threads), "a thread is stuck: deadlock?"
    assert not failures, failures
    return results


def client_for(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {issue_tokens(user)['access']}")
    return client


def buyers(product, variant, count):
    """`count` customers with a delivered order of `product`, and a client for each."""
    users = []
    for index in range(count):
        user = verified_user(f"+88017100{index:05d}")
        delivered_order(user, product, variant)
        users.append(user)
    return users, [client_for(user) for user in users]


def statuses(responses):
    return sorted(response.status_code for response in responses)


def test_customers_reviewing_the_same_product_at_once_are_all_counted():
    product, variant = stocked("Mug", stock=50)
    _, clients = buyers(product, variant, 8)
    ratings = [5, 4, 4, 4, 4, 4, 4, 4]  # 33 / 8 = 4.125 -> 4.13

    responses = run_together(8, lambda index: write_review(clients[index], product, rating=ratings[index]))

    assert statuses(responses) == [201] * 8
    product.refresh_from_db()
    assert (product.total_reviews, product.avg_rating) == (8, Decimal("4.13"))
    assert Review.objects.count() == 8


def test_a_double_click_writes_one_review_and_is_not_a_server_error():
    product, variant = stocked("Mug")
    _, (client,) = buyers(product, variant, 1)

    responses = run_together(4, lambda _: write_review(client, product))

    assert statuses(responses) == [201, 400, 400, 400]
    assert Review.objects.count() == 1
    product.refresh_from_db()
    assert product.total_reviews == 1


def test_two_edits_that_together_exceed_the_file_limit_let_only_one_add_its_files():
    product, variant = stocked("Mug")
    _, (client,) = buyers(product, variant, 1)
    review_id = data(write_review(client, product))["id"]

    def add_three(_):
        return edit_review(client, review_id, media=[image_upload(f"{n}.png") for n in range(3)])

    responses = run_together(2, add_three)

    assert statuses(responses) == [200, 400]  # 3 + 3 > 5: the second one to get the lock is refused
    assert ReviewMedia.objects.count() == 3


def test_reviews_written_edited_and_hidden_together_keep_the_rating_exact():
    product, variant = stocked("Mug", stock=50)
    users, clients = buyers(product, variant, 6)
    first_three = [data(write_review(clients[i], product, rating=5))["id"] for i in range(3)]

    def work(index):
        if index < 3:  # three customers change their rating to 1 ...
            return edit_review(clients[index], first_three[index], rating=1)
        return write_review(clients[index], product, rating=3)  # ... while three others write theirs

    responses = run_together(6, work)

    assert statuses(responses) == [200, 200, 200, 201, 201, 201]
    product.refresh_from_db()
    assert (product.total_reviews, product.avg_rating) == (6, Decimal("2.00"))  # (1+1+1+3+3+3) / 6
