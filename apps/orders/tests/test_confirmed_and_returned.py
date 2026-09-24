"""The two statuses a cash-on-delivery shop needs: `confirmed` (staff checked the order) and `returned` (the shipped
parcel came back: delivery failed or was refused)."""
import pytest

from apps.orders import services
from apps.orders.models import Order, OrderStatusHistory
from apps.orders.tests.helpers import ORDERS, line, make_order, orders_of, signed_in, stock_of, stocked

pytestmark = pytest.mark.django_db

Status = Order.Status


def payment_status(order):
    return list(order.payments.values_list("status", flat=True))


# --- confirmed ---------------------------------------------------------------------------------------------------
def test_confirming_changes_nothing_but_the_status_and_the_history():
    product, variant = stocked(stock=10)
    order = make_order(line(product, variant, 2))
    stock, sold = stock_of(variant), orders_of(product)

    services.change_status(order, Status.CONFIRMED, note="Called the customer.")

    order.refresh_from_db()
    assert order.status == "confirmed"
    assert (stock_of(variant), orders_of(product)) == (stock, sold)  # nothing is taken or given back
    assert payment_status(order) == ["pending"]  # the cash is still to be collected
    row = OrderStatusHistory.objects.filter(order=order).last()
    assert (row.from_status, row.to_status, row.note) == ("pending", "confirmed", "Called the customer.")


def test_a_confirmed_order_goes_on_to_shipped_and_delivered_and_the_cash_is_collected_then():
    product, variant = stocked()
    order = make_order(line(product, variant))
    for status in (Status.CONFIRMED, Status.SHIPPED, Status.DELIVERED):
        services.change_status(order, status)
    assert payment_status(order) == ["paid"]
    assert [row.to_status for row in order.history.all()] == ["pending", "confirmed", "shipped", "delivered"]


def test_a_confirmed_order_that_is_cancelled_goes_back_on_the_shelf():
    product, variant = stocked(stock=10)
    order = make_order(line(product, variant, 3))
    services.change_status(order, Status.CONFIRMED)
    assert stock_of(variant) == 7

    services.change_status(order, Status.CANCELLED)

    assert (stock_of(variant), orders_of(product)) == (10, 0)
    assert payment_status(order) == ["cancelled"]


def test_an_order_can_not_be_confirmed_twice_or_after_it_shipped():
    product, variant = stocked()
    order = make_order(line(product, variant))
    services.change_status(order, Status.CONFIRMED)
    with pytest.raises(services.InvalidTransition):
        services.change_status(order, Status.CONFIRMED)
    services.change_status(order, Status.SHIPPED)
    with pytest.raises(services.InvalidTransition):
        services.change_status(order, Status.CONFIRMED)


# --- returned ----------------------------------------------------------------------------------------------------
def test_a_returned_parcel_goes_back_on_the_shelf_and_its_payment_is_cancelled():
    product, variant = stocked(stock=10)
    order = make_order(line(product, variant, 4))
    services.change_status(order, Status.SHIPPED)
    assert (stock_of(variant), orders_of(product)) == (6, 1)

    services.change_status(order, Status.RETURNED, note="Customer was not at home three times.")

    order.refresh_from_db()
    assert order.status == "returned"
    assert (stock_of(variant), orders_of(product)) == (10, 0)  # the sale does not count: nothing was delivered
    assert payment_status(order) == ["cancelled"]  # no cash was ever collected
    assert order.payments.get().paid_at is None


def test_the_cash_collected_before_shipping_is_refunded_when_the_parcel_comes_back():
    product, variant = stocked()
    order = make_order(line(product, variant))
    for status in (Status.PAID, Status.SHIPPED, Status.RETURNED):
        services.change_status(order, status)
    assert payment_status(order) == ["refunded"]


@pytest.mark.parametrize("start", [Status.PENDING, Status.CONFIRMED, Status.PAID, Status.DELIVERED])
def test_only_a_shipped_parcel_can_be_returned(start):
    product, variant = stocked(stock=10)
    order = make_order(line(product, variant))
    Order.objects.filter(pk=order.pk).update(status=start)
    stock = stock_of(variant)

    with pytest.raises(services.InvalidTransition):
        services.change_status(order, Status.RETURNED)

    assert stock_of(variant) == stock


def test_a_returned_order_is_final_and_a_second_return_does_not_restock_twice():
    product, variant = stocked(stock=10)
    order = make_order(line(product, variant, 2))
    services.change_status(order, Status.SHIPPED)
    services.change_status(order, Status.RETURNED)
    for status in Status.values:
        with pytest.raises(services.InvalidTransition):
            services.change_status(order, status)
    assert stock_of(variant) == 10


# --- what the customer sees --------------------------------------------------------------------------------------
def test_the_customer_sees_the_new_statuses_and_can_not_cancel_a_confirmed_order():
    me, client = signed_in()
    product, variant = stocked(stock=10)
    order = make_order(line(product, variant), user=me)
    services.change_status(order, Status.CONFIRMED)

    data = client.get(f"{ORDERS}{order.number}/").json()["data"]
    assert (data["status"], data["status_display"], data["can_cancel"]) == ("confirmed", "Confirmed", False)

    refused = client.post(f"{ORDERS}{order.number}/cancel/")
    assert refused.status_code == 400 and refused.json()["error"] == services.CANCEL_REFUSED
    order.refresh_from_db()
    assert order.status == "confirmed"  # once staff are handling it, a person decides


def test_a_returned_order_reads_returned_with_its_whole_history(api_client):
    product, variant = stocked()
    order = make_order(line(product, variant))
    for status in (Status.CONFIRMED, Status.SHIPPED, Status.RETURNED):
        services.change_status(order, status, note="internal: courier says the address does not exist")

    response = api_client.get(f"{ORDERS}track/", {"order_id": order.number, "phone_number": "+8801712345678"})

    data = response.json()["data"]
    assert (data["status"], data["status_display"]) == ("returned", "Returned")
    assert [step["status"] for step in data["history"]] == ["pending", "confirmed", "shipped", "returned"]
    assert "courier" not in response.content.decode()  # the staff's note stays with the staff
