"""Three things a customer's orders gained: a status filter on the list, `variant_id` on every line (to buy it again), and
the delivery estimate (what the shop promised, per shipping type, and the dates an order was told to expect)."""
from datetime import date, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.helpers import verified_user
from apps.orders import services
from apps.orders.models import DeliveryCharge, Order
from apps.orders.tests.helpers import CHECKOUT, ORDERS, line, make_order, signed_in, stocked
from apps.orders.tests.test_tracking import track

pytestmark = pytest.mark.django_db


def numbers(response):
    assert response.status_code == 200, response.content
    return [row["order_id"] for row in response.json()["data"]["results"]]


def estimate(inside=(2, 3), outside=(4, 6)):
    for shipping_type, days in (("inside_dhaka", inside), ("outside_dhaka", outside)):
        charge = DeliveryCharge.objects.get(shipping_type=shipping_type)
        charge.min_days, charge.max_days = days if days else (None, None)
        charge.save()


# --- ?status= -----------------------------------------------------------------------------------------------------
@pytest.fixture
def mine():
    """A customer with one order in each of four statuses, newest last: (client, {status: order})."""
    me, client = signed_in("+8801711111111")
    product, _ = stocked(stock=50)
    made = {}
    for status in ("pending", "confirmed", "cancelled", "delivered"):
        order = make_order(line(product), user=me)
        if status != "pending":
            services.change_status(order, Order.Status.CONFIRMED)
        if status == "cancelled":
            services.change_status(order, Order.Status.CANCELLED)
        if status == "delivered":
            services.change_status(order, Order.Status.SHIPPED)
            services.change_status(order, Order.Status.DELIVERED)
        made[status] = order
    return client, made


def test_without_a_status_every_order_comes(mine):
    client, made = mine
    assert set(numbers(client.get(ORDERS))) == {order.number for order in made.values()}
    assert set(numbers(client.get(ORDERS, {"status": ""}))) == {order.number for order in made.values()}


def test_one_status_keeps_only_its_orders(mine):
    client, made = mine
    assert numbers(client.get(ORDERS, {"status": "delivered"})) == [made["delivered"].number]
    assert numbers(client.get(ORDERS, {"status": "cancelled"})) == [made["cancelled"].number]


def test_several_statuses_separated_by_commas(mine):
    client, made = mine
    assert numbers(client.get(ORDERS, {"status": "pending,confirmed"})) == [made["confirmed"].number, made["pending"].number]  # newest first
    assert numbers(client.get(ORDERS, {"status": " Pending , confirmed ,pending"})) == [made["confirmed"].number, made["pending"].number]


def test_a_status_nobody_is_in_is_an_empty_list_not_an_error(mine):
    client, _ = mine
    response = client.get(ORDERS, {"status": "refunded"})
    assert response.status_code == 200 and response.json()["data"] == {"count": 0, "next": None, "previous": None, "results": []}


def test_an_unknown_status_is_a_400_that_names_it(mine):
    client, _ = mine
    response = client.get(ORDERS, {"status": "pending,shipped-ish"})
    assert response.status_code == 400
    assert any("shipped-ish" in str(error) for error in response.json()["errors"])


def test_the_count_and_the_pages_follow_the_filter(mine):
    client, made = mine
    page = client.get(ORDERS, {"status": "pending,confirmed", "page_size": 1}).json()["data"]
    assert page["count"] == 2 and len(page["results"]) == 1 and page["next"] is not None
    assert "status=pending%2Cconfirmed" in page["next"] or "status=pending,confirmed" in page["next"]  # the next page keeps the filter


def test_the_filter_never_shows_somebody_elses_order(mine):
    client, _ = mine
    other = verified_user("+8801722222222")
    product, _unused = stocked("Other", stock=5)
    make_order(line(product), user=other)
    assert len(numbers(client.get(ORDERS, {"status": "pending"}))) == 1


# --- variant_id ---------------------------------------------------------------------------------------------------
def test_every_line_says_which_variant_it_was_so_it_can_be_bought_again():
    me, client = signed_in("+8801711111111")
    product, variant = stocked("Mug", stock=10)
    order = make_order(line(product, variant, 2), user=me)

    listed = client.get(ORDERS).json()["data"]["results"][0]["items"][0]
    detail = client.get(f"{ORDERS}{order.number}/").json()["data"]["items"][0]

    assert (listed["product_id"], listed["variant_id"]) == (product.pk, variant.pk)
    assert (detail["product_id"], detail["variant_id"]) == (product.pk, variant.pk)


def test_a_guest_tracking_an_order_gets_it_too(api_client):
    product, variant = stocked("Mug", stock=10)
    order = make_order(line(product, variant))

    assert track(api_client, order.number).json()["data"]["items"][0]["variant_id"] == variant.pk


def test_it_is_null_once_the_variant_is_deleted_and_the_snapshot_stays():
    me, client = signed_in("+8801711111111")
    product, variant = stocked("Mug", stock=10)
    order = make_order(line(product, variant), user=me)
    variant.delete()

    item = client.get(f"{ORDERS}{order.number}/").json()["data"]["items"][0]

    assert item["variant_id"] is None and item["product_name"] == "Mug"


# --- the delivery estimate ------------------------------------------------------------------------------------------
def test_checkout_tells_how_long_delivery_takes_only_where_the_shop_said():
    estimate(inside=(2, 3), outside=None)

    body = signed_in()[1].get(CHECKOUT).json()["data"]

    assert body["delivery_estimates"] == {"inside_dhaka": {"min_days": 2, "max_days": 3}}  # outside: no promise, nothing said


def test_a_new_shop_makes_no_promise_until_it_sets_the_days(api_client):
    assert api_client.get(CHECKOUT).json()["data"]["delivery_estimates"] == {}


def test_a_placed_order_is_told_the_dates_and_keeps_them():
    estimate(inside=(2, 3))
    me, client = signed_in("+8801711111111")
    product, variant = stocked("Mug", stock=10)
    today = timezone.localdate()

    order = make_order(line(product, variant), user=me)

    assert (order.expected_from, order.expected_to) == (today + timedelta(days=2), today + timedelta(days=3))
    estimate(inside=(7, 9))  # the shop changes its mind: this order was already promised
    order.refresh_from_db()
    assert order.expected_to == today + timedelta(days=3)
    shown = client.get(f"{ORDERS}{order.number}/").json()["data"]["expected_delivery"]
    assert shown == {"earliest": str(today + timedelta(days=2)), "latest": str(today + timedelta(days=3))}


def test_the_answer_to_placing_an_order_has_the_dates_for_the_confirmation_page(api_client):
    estimate(inside=(1, 2))
    product, variant = stocked("Mug", stock=10)
    from apps.orders.tests.test_place_order import place

    body = place(api_client, line(product, variant)).json()["data"]

    today = timezone.localdate()
    assert body["expected_delivery"] == {"earliest": str(today + timedelta(days=1)), "latest": str(today + timedelta(days=2))}


def test_an_estimate_of_the_same_day_is_a_day_not_a_range():
    estimate(inside=(2, 2))
    product, _ = stocked("Mug", stock=10)
    order = make_order(line(product))
    assert order.expected_from == order.expected_to == timezone.localdate() + timedelta(days=2)


def test_no_estimate_means_no_dates_and_a_null_in_the_answer():
    me, client = signed_in("+8801711111111")
    product, _ = stocked("Mug", stock=10)
    order = make_order(line(product), user=me)

    assert (order.expected_from, order.expected_to) == (None, None)
    assert client.get(f"{ORDERS}{order.number}/").json()["data"]["expected_delivery"] is None


@pytest.mark.parametrize(
    "status, shown",
    [("pending", True), ("confirmed", True), ("paid", True), ("shipped", True), ("delivered", False), ("cancelled", False), ("returned", False), ("refunded", False)],
)
def test_it_is_only_expected_while_the_order_is_on_its_way(status, shown):
    order = Order(status=status, expected_from=date(2026, 10, 5), expected_to=date(2026, 10, 7))
    assert (services.expected_delivery(order) is not None) is shown


def test_a_guest_tracking_an_order_sees_when_to_expect_it(api_client):
    estimate(inside=(2, 3))
    product, _ = stocked("Mug", stock=10)
    order = make_order(line(product))

    assert track(api_client, order.number).json()["data"]["expected_delivery"]["latest"] == str(timezone.localdate() + timedelta(days=3))


def test_the_database_wants_both_days_or_neither_and_in_order():
    charge = DeliveryCharge.objects.get(shipping_type="inside_dhaka")
    for low, high in ((2, None), (None, 3), (5, 3)):
        charge.min_days, charge.max_days = low, high
        with pytest.raises(IntegrityError), transaction.atomic():
            charge.save()


def test_the_form_check_says_so_in_words():
    charge = DeliveryCharge.objects.get(shipping_type="inside_dhaka")
    charge.min_days, charge.max_days = 5, 3
    with pytest.raises(ValidationError) as caught:
        charge.full_clean()
    assert "Give both the fewest and the most days" in str(caught.value)
    charge.min_days, charge.max_days = 1, 61
    with pytest.raises(ValidationError):
        charge.full_clean()  # two months is not a delivery estimate


def test_staff_set_the_days_in_the_admin(client):
    from django.contrib.auth import get_user_model

    staff = get_user_model().objects.create_superuser("+8801700000000", password="s3cret-Pass!", name="Root")
    client.force_login(staff)
    charge = DeliveryCharge.objects.get(shipping_type="inside_dhaka")

    listing = client.get(reverse("admin:orders_deliverycharge_changelist")).content.decode()
    assert "no estimate" in listing

    response = client.post(
        reverse("admin:orders_deliverycharge_change", args=[charge.pk]), {"amount": "60.00", "min_days": "2", "max_days": "3"}
    )
    assert response.status_code == 302
    charge.refresh_from_db()
    assert (charge.min_days, charge.max_days) == (2, 3)
    assert "2-3 days" in client.get(reverse("admin:orders_deliverycharge_changelist")).content.decode()

    refused = client.post(reverse("admin:orders_deliverycharge_change", args=[charge.pk]), {"amount": "60.00", "min_days": "5", "max_days": "3"})
    assert refused.status_code == 200 and "Give both the fewest and the most days" in refused.content.decode()
