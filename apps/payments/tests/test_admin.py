import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.orders.models import Order
from apps.payments.models import Payment
from apps.payments.tests.helpers import move, payment_of, placed

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client():
    user = get_user_model().objects.create_superuser("+8801700000000", password="s3cret-Pass!", name="Root")
    client = Client()
    client.force_login(user)
    return client


def run_order_action(client, action, order):
    return client.post(
        reverse("admin:orders_order_changelist"),
        {"action": action, "_selected_action": [str(order.pk)], "index": "0"},
        follow=True,
    )


def test_the_ledger_lists_payments_and_finds_them_by_order_number_and_status(admin_client):
    order, _ = placed()
    url = reverse("admin:payments_payment_changelist")
    html = admin_client.get(url).content.decode()
    assert order.number in html and "Cash on delivery" in html
    assert order.number in admin_client.get(url, {"q": order.number}).content.decode()
    assert order.number not in admin_client.get(url, {"status__exact": "paid"}).content.decode()


def test_a_payment_can_be_looked_at_but_never_added_edited_or_deleted(admin_client):
    order, _ = placed()
    payment = payment_of(order)
    assert admin_client.get(reverse("admin:payments_payment_add")).status_code == 403
    assert admin_client.get(reverse("admin:payments_payment_change", args=[payment.pk])).status_code == 200
    change = reverse("admin:payments_payment_change", args=[payment.pk])
    assert admin_client.post(change, {"status": "paid"}).status_code == 403
    assert admin_client.get(reverse("admin:payments_payment_delete", args=[payment.pk])).status_code == 403
    payment.refresh_from_db()
    assert payment.status == "pending"


def test_staff_marking_an_order_delivered_collects_the_payment(admin_client):
    order, _ = placed()
    move(order, Order.Status.SHIPPED)
    run_order_action(admin_client, "mark_delivered", order)
    assert payment_of(order).status == "paid"


def test_staff_cancelling_an_order_cancels_the_payment_and_marking_it_paid_pays_it(admin_client):
    cancelled, _ = placed()
    run_order_action(admin_client, "cancel_and_restock", cancelled)
    assert payment_of(cancelled).status == "cancelled"

    paid, _ = placed()
    run_order_action(admin_client, "mark_paid", paid)
    assert payment_of(paid).status == "paid"
