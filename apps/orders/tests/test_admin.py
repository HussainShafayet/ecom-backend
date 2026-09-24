import re
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.orders import services
from apps.orders.models import DeliveryCharge, Order
from apps.orders.tests.helpers import line, make_order, orders_of, stock_of, stocked

pytestmark = pytest.mark.django_db

Status = Order.Status


@pytest.fixture
def staff():
    return get_user_model().objects.create_superuser("+8801700000000", password="s3cret-Pass!", name="Root")


@pytest.fixture
def admin_client(staff):
    client = Client()
    client.force_login(staff)
    return client


def change_url(order):
    return reverse("admin:orders_order_change", args=[order.pk])


LIST_URL = "orders_order_changelist"


def form_data(order, **fields):
    """What the browser posts from an order's page: the status, plus the management forms of the two read-only
    inlines (items and history), which the admin insists on."""
    data = {"status": order.status}
    for prefix, total in (("items", order.items.count()), ("history", order.history.count())):
        data |= {
            f"{prefix}-TOTAL_FORMS": str(total),
            f"{prefix}-INITIAL_FORMS": str(total),
            f"{prefix}-MIN_NUM_FORMS": "0",
            f"{prefix}-MAX_NUM_FORMS": "0",
        }
    data.update(fields)
    return data


def offered_statuses(html):
    select = re.search(r'<select name="status".*?</select>', html, re.S).group(0)
    return re.findall(r'<option value="(\w+)"', select)


def messages_of(response):
    return [str(message) for message in response.context["messages"]]


def run_action(client, action, *orders):
    return client.post(
        reverse(f"admin:{LIST_URL}"),
        {"action": action, "_selected_action": [str(order.pk) for order in orders], "index": "0"},
        follow=True,
    )


@pytest.fixture
def order():
    mug, variant = stocked("Mug", stock=10, base_price="500.00")
    order = make_order(
        line(mug, variant, 2), name="Karim Ali", email="karim@example.com", phone_number="+8801811111111"
    )
    order.mug, order.variant = mug, variant
    return order


# --- the list -------------------------------------------------------------------------------------------------
def test_the_list_shows_orders_with_number_customer_status_and_total(admin_client, order):
    html = admin_client.get(reverse(f"admin:{LIST_URL}")).content.decode()
    for text in (order.number, "Karim Ali", "+8801811111111", "Pending", "1060.00"):
        assert text in html


@pytest.mark.parametrize("term", ["Karim", "+8801811111111", "karim@example.com", "-0001"])
def test_orders_can_be_found_by_name_phone_email_and_number(admin_client, order, term):
    other, _ = stocked("Other")
    make_order(line(other), name="Someone Else", email="s@example.com", phone_number="+8801922222222")
    html = admin_client.get(reverse(f"admin:{LIST_URL}"), {"q": term}).content.decode()
    assert order.number in html
    if term != "-0001":
        assert "Someone Else" not in html


def test_the_list_filters_by_status(admin_client, order):
    other, _ = stocked("Other")
    second = make_order(line(other))
    services.change_status(second, Status.PAID)
    html = admin_client.get(reverse(f"admin:{LIST_URL}"), {"status__exact": "paid"}).content.decode()
    assert second.number in html and order.number not in html


# --- the order page -------------------------------------------------------------------------------------------
def test_the_page_shows_everything_but_only_the_status_can_be_edited(admin_client, order):
    html = admin_client.get(change_url(order)).content.decode()

    shown = (order.number, "Karim Ali", "karim@example.com", "House 12, Road 5", "Gulshan", "Mug", "500.00", "1060.00")
    for text in shown:
        assert text in html
    assert "Order placed." in html  # the history row
    editable = re.findall(r'<(?:input|select|textarea)[^>]*name="([^"]+)"', html)
    assert [name for name in editable if not name.startswith(("csrf", "_", "items-", "history-"))] == ["status"]


@pytest.mark.parametrize(
    "status, expected",
    [
        ("pending", ["pending", "confirmed", "paid", "shipped", "cancelled"]),
        ("confirmed", ["confirmed", "paid", "shipped", "cancelled"]),
        ("paid", ["paid", "shipped", "cancelled", "refunded"]),
        ("shipped", ["shipped", "delivered", "returned", "cancelled"]),
        ("delivered", ["delivered", "refunded"]),
        ("returned", ["returned"]),
        ("cancelled", ["cancelled"]),
        ("refunded", ["refunded"]),
    ],
)
def test_the_status_offers_the_current_one_and_the_allowed_next_ones(admin_client, order, status, expected):
    Order.objects.filter(pk=order.pk).update(status=status)
    assert sorted(offered_statuses(admin_client.get(change_url(order)).content.decode())) == sorted(expected)


def test_changing_the_status_goes_through_the_service(admin_client, staff, order):
    response = admin_client.post(change_url(order), form_data(order, status="shipped"))

    assert response.status_code == 302, response.content.decode()[:3000]
    order.refresh_from_db()
    assert order.status == "shipped"
    row = order.history.last()
    assert (row.from_status, row.to_status, row.changed_by) == ("pending", "shipped", staff)
    assert row.note == "Changed in the admin."


def test_cancelling_from_the_form_puts_the_goods_back(admin_client, order):
    assert stock_of(order.variant) == 8
    admin_client.post(change_url(order), form_data(order, status="cancelled"))
    assert stock_of(order.variant) == 10 and orders_of(order.mug) == 0
    assert Order.objects.get(pk=order.pk).status == "cancelled"


def test_a_status_the_flow_does_not_allow_is_refused_in_the_form(admin_client, order):
    response = admin_client.post(change_url(order), form_data(order, status="delivered"))

    assert response.status_code == 200  # the form again
    assert "Select a valid choice" in response.content.decode()
    order.refresh_from_db()
    assert order.status == "pending" and order.history.count() == 1


def test_saving_without_a_change_writes_no_history(admin_client, order):
    assert admin_client.post(change_url(order), form_data(order)).status_code == 302
    order.refresh_from_db()
    assert order.status == "pending" and order.history.count() == 1
    assert stock_of(order.variant) == 8


def test_the_other_fields_can_not_be_changed_by_posting_them(admin_client, order):
    admin_client.post(
        change_url(order),
        form_data(order, name="Hacker", total="1.00", subtotal="1.00", shipping_address="Elsewhere", number="X-1"),
    )
    fresh = Order.objects.get(pk=order.pk)
    assert (fresh.name, fresh.total, fresh.shipping_address, fresh.number) == (
        "Karim Ali",
        Decimal("1060.00"),
        "House 12, Road 5",
        order.number,
    )


def test_a_lost_race_shows_an_error_and_changes_nothing(admin_client, order, monkeypatch):
    """Somebody else moved the order between the form check and the save: the service refuses, the page says so."""

    def refuse(order, new_status, by=None, note=""):
        raise services.InvalidTransition("cancelled", new_status)

    monkeypatch.setattr(services, "change_status", refuse)
    response = admin_client.post(change_url(order), form_data(order, status="shipped"), follow=True)
    assert any("can not become shipped" in message and order.number in message for message in messages_of(response))
    assert Order.objects.get(pk=order.pk).status == "pending"


def test_an_order_can_neither_be_added_nor_deleted(admin_client, order):
    assert admin_client.get(reverse("admin:orders_order_add")).status_code == 403
    assert admin_client.get(reverse("admin:orders_order_delete", args=[order.pk])).status_code == 403
    assert admin_client.post(reverse("admin:orders_order_delete", args=[order.pk]), {"post": "yes"}).status_code == 403
    assert Order.objects.filter(pk=order.pk).exists()
    page = admin_client.get(change_url(order)).content.decode()
    assert "/delete/" not in page
    listing = admin_client.get(reverse(f"admin:{LIST_URL}")).content.decode()
    assert "delete_selected" not in listing and "Add order" not in listing


def test_the_items_and_the_history_are_read_only_inlines(admin_client, order):
    html = admin_client.get(change_url(order)).content.decode()
    assert "Order items" in html and "Status history" in html
    assert 'name="items-0-quantity"' not in html and 'name="history-0-note"' not in html
    assert "add-row" not in html and "delete-row" not in html  # no way to add or remove a line


# --- the actions ----------------------------------------------------------------------------------------------
def test_the_actions_are_offered(admin_client, order):
    html = admin_client.get(reverse(f"admin:{LIST_URL}")).content.decode()
    labels = ("Mark as confirmed", "Mark as paid", "Mark as shipped", "Mark as delivered", "Mark as returned", "Cancel and restock")
    for label in labels:
        assert label in html


@pytest.mark.parametrize(
    "action, start, expected, message",
    [
        ("mark_confirmed", "pending", "confirmed", "1 order(s) marked as confirmed."),
        ("mark_paid", "pending", "paid", "1 order(s) marked as paid."),
        ("mark_paid", "confirmed", "paid", "1 order(s) marked as paid."),
        ("mark_returned", "shipped", "returned", "1 order(s) marked as returned and put back in stock."),
        ("mark_shipped", "paid", "shipped", "1 order(s) marked as shipped."),
        ("mark_delivered", "shipped", "delivered", "1 order(s) marked as delivered."),
        ("cancel_and_restock", "paid", "cancelled", "1 order(s) cancelled and put back in stock."),
    ],
)
def test_each_action_moves_the_orders_through_the_service(admin_client, staff, order, action, start, expected, message):
    Order.objects.filter(pk=order.pk).update(status=start)

    response = run_action(admin_client, action, order)

    assert message in messages_of(response)
    order.refresh_from_db()
    assert order.status == expected
    row = order.history.last()
    assert (row.from_status, row.to_status, row.changed_by) == (start, expected, staff)


def test_mark_as_returned_gives_the_goods_back_and_only_works_on_a_shipped_parcel(admin_client, order):
    services.change_status(order, Status.SHIPPED)
    assert stock_of(order.variant) == 8
    run_action(admin_client, "mark_returned", order)
    assert stock_of(order.variant) == 10 and orders_of(order.mug) == 0

    other, _ = stocked("Other")
    pending = make_order(line(other))
    response = run_action(admin_client, "mark_returned", pending)
    assert f"{pending.number}: A pending order can not become returned." in messages_of(response)


def test_cancel_and_restock_gives_the_goods_back(admin_client, order):
    run_action(admin_client, "cancel_and_restock", order)
    assert stock_of(order.variant) == 10 and orders_of(order.mug) == 0


def test_an_action_reports_each_order_it_could_not_change_and_still_does_the_rest(admin_client, order):
    other, _ = stocked("Other")
    shipped = make_order(line(other))
    services.change_status(shipped, Status.SHIPPED)

    response = run_action(admin_client, "mark_delivered", order, shipped)

    messages = messages_of(response)
    assert "1 order(s) marked as delivered." in messages
    assert f"{order.number}: A pending order can not become delivered." in messages
    order.refresh_from_db(), shipped.refresh_from_db()
    assert (order.status, shipped.status) == ("pending", "delivered")


def test_cancelling_twice_never_restocks_twice(admin_client, order):
    run_action(admin_client, "cancel_and_restock", order)
    response = run_action(admin_client, "cancel_and_restock", order)
    assert f"{order.number}: A cancelled order can not become cancelled." in messages_of(response)
    assert stock_of(order.variant) == 10


def test_an_action_over_several_orders_changes_them_all(admin_client, order):
    others = [make_order(line(stocked(f"P{i}")[0])) for i in range(3)]
    response = run_action(admin_client, "mark_shipped", order, *others)
    assert "4 order(s) marked as shipped." in messages_of(response)
    assert set(Order.objects.values_list("status", flat=True)) == {"shipped"}


# --- delivery charges -----------------------------------------------------------------------------------------
def charge_url(shipping_type):
    charge = DeliveryCharge.objects.get(shipping_type=shipping_type)
    return reverse("admin:orders_deliverycharge_change", args=[charge.pk])


def test_the_two_charges_are_listed_and_the_amount_can_be_edited(admin_client):
    html = admin_client.get(reverse("admin:orders_deliverycharge_changelist")).content.decode()
    assert "Inside Dhaka" in html and "Outside Dhaka" in html and "60.00" in html and "120.00" in html

    response = admin_client.post(charge_url("inside_dhaka"), {"amount": "75.50"})

    assert response.status_code == 302
    assert DeliveryCharge.objects.get(shipping_type="inside_dhaka").amount == Decimal("75.50")


def test_only_the_amount_is_editable(admin_client):
    admin_client.post(charge_url("inside_dhaka"), {"amount": "70", "shipping_type": "outside_dhaka"})
    charge = DeliveryCharge.objects.get(pk=DeliveryCharge.objects.order_by("id").first().pk)
    assert (charge.shipping_type, charge.amount) == ("inside_dhaka", Decimal("70.00"))
    assert DeliveryCharge.objects.filter(shipping_type="outside_dhaka").count() == 1


def test_a_negative_amount_is_refused(admin_client):
    response = admin_client.post(charge_url("inside_dhaka"), {"amount": "-5"})
    assert response.status_code == 200 and "greater than or equal to 0" in response.content.decode()
    assert DeliveryCharge.objects.get(shipping_type="inside_dhaka").amount == Decimal("60.00")


def test_charges_can_neither_be_added_nor_deleted(admin_client):
    charge = DeliveryCharge.objects.first()
    assert admin_client.get(reverse("admin:orders_deliverycharge_add")).status_code == 403
    assert admin_client.get(reverse("admin:orders_deliverycharge_delete", args=[charge.pk])).status_code == 403
    assert DeliveryCharge.objects.count() == 2


def test_a_new_amount_applies_to_the_next_order_only(admin_client, order):
    admin_client.post(charge_url("inside_dhaka"), {"amount": "99"})
    later = make_order(line(order.mug, order.variant))
    order.refresh_from_db()
    assert order.delivery_charge == Decimal("60.00") and later.delivery_charge == Decimal("99.00")
