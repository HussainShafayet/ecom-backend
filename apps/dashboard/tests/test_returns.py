"""The dashboard's returns: money paid back, net revenue, the courier the shop pays, and the units that came back."""
import itertools
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.dashboard import services
from apps.orders.models import Order
from apps.orders.tests.helpers import line, signed_in, stocked
from apps.payments.models import Payment
from apps.returns import services as return_services
from apps.returns.models import ReturnRequest
from apps.returns.tests.helpers import body, delivered_order, returns_url

pytestmark = pytest.mark.django_db

Status = ReturnRequest.Status
_customers = itertools.count(1)


def returned(reason="changed_mind", units=1, finish=True, good=None, damaged=0, price="500.00", quantity=3):
    """A delivered order (paid: cash collected at the door) with a request for `units` of its line, received (and completed when `finish`)."""
    me, client = signed_in(f"+880171{next(_customers):07d}")  # a new customer each time: a test may make several returns
    mug, _ = stocked("Mug", stock=50, base_price=price)
    order = delivered_order(me, line(mug, quantity=quantity))
    client.post(returns_url(order), body(order, (0, units), reason=reason), format="json")
    request = ReturnRequest.objects.get(order=order)
    return_services.change_status(request, Status.APPROVED)
    item = request.items.get()
    return_services.receive_goods(request, [{"item_id": item.pk, "good": units if good is None else good, "damaged": damaged}])
    if finish:
        return_services.change_status(request, Status.COMPLETED)
    return request


def test_the_money_paid_back_comes_off_revenue_in_its_own_line():
    request = returned(units=2)  # goods 1000, the customer's own reason: charge 60, refund 940; the order was paid 1500 + 60 = 1560

    assert services.revenue_summary()["all"] == Decimal("1560.00")
    assert services.refund_summary()["all"] == Decimal("940.00")
    context = services.dashboard_context("all", 20)
    assert context["net_revenue"]["all"] == Decimal("620.00")
    assert (context["net_revenue"]["today"], context["refunds"]["month"]) == (Decimal("620.00"), Decimal("940.00"))
    assert request.status == "completed"


def test_a_request_not_yet_completed_has_not_paid_anything_back():
    returned(units=2, finish=False)
    assert services.refund_summary()["all"] == Decimal("0.00")


def test_a_refund_completed_last_month_is_not_in_this_months_buckets():
    request = returned(units=2)
    ReturnRequest.objects.filter(pk=request.pk).update(completed_at=timezone.now() - timezone.timedelta(days=40))

    refunds = services.refund_summary()

    assert (refunds["today"], refunds["week"], refunds["month"], refunds["all"]) == (0, 0, 0, Decimal("940.00"))


def test_an_order_that_was_also_marked_refunded_is_not_taken_off_twice():
    request = returned(units=3)
    order = request.order
    assert services.refund_summary()["all"] == Decimal("1440.00")  # goods 1500, charge 60
    revenue_before = services.revenue_summary()["all"]  # 1560

    from apps.orders import services as order_services

    order_services.change_status(order, Order.Status.REFUNDED)  # staff: everything came back, refund the whole order

    assert Payment.objects.get(order=order).status == "refunded"
    assert revenue_before == Decimal("1560.00") and services.revenue_summary()["all"] == Decimal("0.00")  # the payment left revenue by itself
    assert services.refund_summary()["all"] == Decimal("0.00")  # so its return refund is not taken off again
    assert services.dashboard_context("all", 20)["net_revenue"]["all"] == Decimal("0.00")


def test_the_courier_the_shop_pays_is_what_the_customer_did_not_pay_of_it():
    returned(reason="changed_mind")  # the customer pays the 60 delivery: the shop pays nothing
    assert services.returns_summary(None)["shop_courier_cost"] == Decimal("0.00")
    returned(reason="damaged")  # free: the shop pays the whole 60
    assert services.returns_summary(None)["shop_courier_cost"] == Decimal("60.00")


def test_a_waived_charge_is_the_shops_cost():
    request = returned(reason="changed_mind", finish=False)
    return_services.staff_update(request, return_charge=Decimal("20.00"))  # the customer pays 20 of the 60
    assert services.returns_summary(None)["shop_courier_cost"] == Decimal("40.00")


def test_the_units_back_on_the_shelf_and_the_damaged_ones_are_counted_apart():
    returned(reason="damaged", units=3, good=1, damaged=2, finish=False)
    returned(reason="size_fit", units=1)

    summary = services.returns_summary(None)

    assert (summary["received"], summary["restocked_units"], summary["damaged_units"]) == (2, 2, 2)


def test_a_request_that_has_not_come_back_is_not_counted_as_a_return():
    me, client = signed_in()
    mug, _ = stocked(stock=10)
    order = delivered_order(me, line(mug, quantity=2))
    client.post(returns_url(order), body(order, (0, 2)), format="json")
    return_services.change_status(ReturnRequest.objects.get(), Status.APPROVED)  # agreed, goods not here yet

    summary = services.returns_summary(None)

    assert (summary["received"], summary["restocked_units"], summary["shop_courier_cost"]) == (0, 0, Decimal("0.00"))


def test_the_period_narrows_the_returns_to_those_received_in_it():
    request = returned(reason="damaged")
    ReturnRequest.objects.filter(pk=request.pk).update(received_at=timezone.now() - timezone.timedelta(days=40))

    assert services.returns_summary(timezone.localdate())["received"] == 0
    assert services.returns_summary(None)["received"] == 1


def test_the_page_shows_the_new_lines():
    returned(reason="damaged", units=2, good=1, damaged=1)
    user = get_user_model().objects.create_superuser("+8801700000000", password="s3cret-Pass!", name="Root")
    client = Client()
    client.force_login(user)

    html = client.get(reverse("admin:dashboard_dashboardreport_changelist"), {"period": "all"}).content.decode()

    for text in ("Refunded for returns", "Net revenue", "Returns &mdash; all time", "Courier paid by the shop", "Units damaged"):
        assert text in html
