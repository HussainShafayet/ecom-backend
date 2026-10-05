"""The goods come back: `services.receive_goods` records what arrived (fine / damaged), puts the fine units back on the shelf, counts the
damaged ones and moves the request to `received`; `orders.services.take_back_stock` is the stock part."""
import pytest
from django.db import IntegrityError

from apps.catalog.models import ProductVariant
from apps.orders import services as order_services
from apps.orders.models import Order
from apps.orders.tests.helpers import line, make_order, orders_of, signed_in, stock_of, stocked
from apps.orders.tests.test_concurrency import run_together
from apps.returns import services
from apps.returns.models import ReturnItem, ReturnRequest

from .helpers import body, delivered_order, returns_url

pytestmark = pytest.mark.django_db

Status = ReturnRequest.Status


def damaged_of(variant):
    variant.refresh_from_db()
    return variant.damaged_quantity


def asked_for(entries, reason="damaged", stocks=(10, 10)):
    """Two variants (a Mug of 3 and a Shirt of 2 ordered, `stocks` on the shelf before), a delivered order of them and an approved
    request for `entries` (`(line index, units)`). Returns (request, mug variant, shirt variant, order)."""
    me, client = signed_in()
    mug, mug_v = stocked("Mug", stock=stocks[0], base_price="500.00")
    shirt, shirt_v = stocked("Shirt", stock=stocks[1], base_price="300.00")
    order = delivered_order(me, line(mug, mug_v, 3), line(shirt, shirt_v, 2))
    client.post(returns_url(order), body(order, *entries, reason=reason), format="json")
    request = ReturnRequest.objects.get(order=order)
    services.change_status(request, Status.APPROVED)
    return request, mug_v, shirt_v, order


def lines_for(request, **by_name):
    """`{"Mug": (good, damaged)}` -> the lines `receive_goods` takes."""
    return [
        {"item_id": item.pk, "good": by_name[item.order_item.product_name][0], "damaged": by_name[item.order_item.product_name][1]}
        for item in request.items.select_related("order_item")
        if item.order_item.product_name in by_name
    ]


# --- the stock --------------------------------------------------------------------------------------------------
def test_the_units_that_came_back_fine_go_back_on_the_shelf():
    request, mug_v, shirt_v, _ = asked_for([(0, 2), (1, 1)])
    before = (stock_of(mug_v), stock_of(shirt_v))  # 7 and 8 left after the order

    result = services.receive_goods(request, lines_for(request, Mug=(2, 0), Shirt=(1, 0)))

    assert result == {"restocked": 3, "damaged": 0, "unplaced": []}
    assert (stock_of(mug_v), stock_of(shirt_v)) == (before[0] + 2, before[1] + 1)
    assert (damaged_of(mug_v), damaged_of(shirt_v)) == (0, 0)


def test_the_damaged_units_are_counted_but_never_added_to_the_stock():
    request, mug_v, _, _ = asked_for([(0, 3)])
    before = stock_of(mug_v)

    result = services.receive_goods(request, lines_for(request, Mug=(1, 2)))

    assert result == {"restocked": 1, "damaged": 2, "unplaced": []}
    assert stock_of(mug_v) == before + 1  # only the fine one is for sale again
    assert damaged_of(mug_v) == 2  # the other two are on record as lost


def test_everything_damaged_changes_no_stock_at_all():
    request, mug_v, _, _ = asked_for([(0, 1)])
    before = stock_of(mug_v)

    services.receive_goods(request, lines_for(request, Mug=(0, 1)))

    assert (stock_of(mug_v), damaged_of(mug_v)) == (before, 1)


def test_the_counters_add_up_over_several_returns():
    request, mug_v, _, order = asked_for([(0, 1)])
    services.receive_goods(request, lines_for(request, Mug=(0, 1)))
    second = ReturnRequest.objects.create(order=order, reason="damaged", goods_amount=0, courier_cost=0, return_charge=0, refund_amount=0, status="approved")
    ReturnItem.objects.create(request=second, order_item=order.items.first(), quantity=1)

    services.receive_goods(second, [{"item_id": second.items.get().pk, "good": 0, "damaged": 1}])

    assert damaged_of(mug_v) == 2


def test_a_line_left_out_came_back_with_nothing():
    request, mug_v, shirt_v, _ = asked_for([(0, 2), (1, 2)])
    before = (stock_of(mug_v), stock_of(shirt_v))

    services.receive_goods(request, lines_for(request, Mug=(2, 0)))  # the shirts never arrived

    assert (stock_of(mug_v), stock_of(shirt_v)) == (before[0] + 2, before[1])
    shirts = request.items.get(order_item__product_name="Shirt")
    assert (shirts.good_quantity, shirts.damaged_quantity) == (0, 0)


def test_fewer_units_than_asked_for_is_fine():
    request, mug_v, _, _ = asked_for([(0, 3)])
    before = stock_of(mug_v)
    services.receive_goods(request, lines_for(request, Mug=(1, 1)))  # 2 of the 3 arrived
    assert stock_of(mug_v) == before + 1


def test_what_came_back_is_recorded_per_line():
    request, _, _, _ = asked_for([(0, 3), (1, 1)])

    services.receive_goods(request, lines_for(request, Mug=(2, 1), Shirt=(0, 1)))

    rows = {item.order_item.product_name: (item.good_quantity, item.damaged_quantity) for item in request.items.select_related("order_item")}
    assert rows == {"Mug": (2, 1), "Shirt": (0, 1)}


def test_the_request_becomes_received_with_the_time_and_nothing_else_about_the_order_changes():
    request, mug_v, _, order = asked_for([(0, 2)])
    sold, payments = orders_of(mug_v.product), list(order.payments.values_list("status", flat=True))

    services.receive_goods(request, lines_for(request, Mug=(2, 0)))

    request.refresh_from_db()
    assert (request.status, request.completed_at) == ("received", None) and request.received_at is not None
    order.refresh_from_db()
    assert order.status == "delivered"
    assert orders_of(mug_v.product) == sold  # the sale still happened
    assert list(order.payments.values_list("status", flat=True)) == payments


# --- when it is refused -----------------------------------------------------------------------------------------
def test_a_request_that_is_not_approved_can_not_be_received():
    me, client = signed_in()
    mug, mug_v = stocked(stock=10)
    order = delivered_order(me, line(mug, mug_v, 2))
    client.post(returns_url(order), body(order, (0, 2)), format="json")
    request = ReturnRequest.objects.get()  # still requested
    before = stock_of(mug_v)

    with pytest.raises(services.InvalidTransition):
        services.receive_goods(request, [{"item_id": request.items.get().pk, "good": 2, "damaged": 0}])

    assert (stock_of(mug_v), ReturnRequest.objects.get().status) == (before, "requested")


def test_a_request_can_be_received_only_once_so_the_stock_moves_only_once():
    request, mug_v, _, _ = asked_for([(0, 2)])
    services.receive_goods(request, lines_for(request, Mug=(2, 0)))
    after = stock_of(mug_v)

    with pytest.raises(services.InvalidTransition):
        services.receive_goods(request, lines_for(request, Mug=(2, 0)))

    assert stock_of(mug_v) == after


@pytest.mark.parametrize(
    "good, damaged, sentence",
    [
        (3, 0, "Mug (Default): 3 units can not come back, only 2 were asked for."),
        (1, 2, "Mug (Default): 3 units can not come back, only 2 were asked for."),
        (0, 3, "Mug (Default): 3 units can not come back, only 2 were asked for."),
        (-1, 0, "Mug (Default): a number of units can not be negative."),
        (0, 0, services.NOTHING_CAME_BACK),
    ],
)
def test_wrong_numbers_are_refused_with_a_sentence_and_nothing_is_written(good, damaged, sentence):
    request, mug_v, _, _ = asked_for([(0, 2)])
    before = (stock_of(mug_v), damaged_of(mug_v))

    with pytest.raises(services.ValidationError) as refused:
        services.receive_goods(request, lines_for(request, Mug=(good, damaged)))

    assert [str(detail) for detail in refused.value.detail] == [sentence]
    assert (stock_of(mug_v), damaged_of(mug_v)) == before
    request.refresh_from_db()
    assert (request.status, request.received_at) == ("approved", None)
    assert request.items.get().good_quantity == 0


def test_every_problem_is_reported_together_and_not_one_unit_moves():
    request, mug_v, shirt_v, _ = asked_for([(0, 2), (1, 2)])
    before = (stock_of(mug_v), stock_of(shirt_v))

    with pytest.raises(services.ValidationError) as refused:
        services.receive_goods(request, lines_for(request, Mug=(2, 1), Shirt=(5, 0)) + [{"item_id": 99999, "good": 1, "damaged": 0}])

    sentences = [str(detail) for detail in refused.value.detail]
    assert "Mug (Default): 3 units can not come back, only 2 were asked for." in sentences
    assert "Shirt (Default): 5 units can not come back, only 2 were asked for." in sentences
    assert "One of those lines is not in this request." in sentences
    assert (stock_of(mug_v), stock_of(shirt_v)) == before


def test_the_database_itself_refuses_more_units_than_were_asked_for():
    request, _, _, _ = asked_for([(0, 2)])
    item = request.items.get()
    item.good_quantity, item.damaged_quantity = 2, 1
    with pytest.raises(IntegrityError):
        item.save()


# --- deleted from the catalog ----------------------------------------------------------------------------------
def test_units_of_a_variant_that_was_deleted_since_are_recorded_but_there_is_no_stock_to_give_them_back_to():
    request, mug_v, shirt_v, _ = asked_for([(0, 2), (1, 1)])
    ProductVariant.objects.filter(pk=mug_v.pk).delete()  # the order line keeps its snapshot, its variant link becomes empty
    before = stock_of(shirt_v)

    result = services.receive_goods(request, lines_for(request, Mug=(2, 0), Shirt=(1, 0)))

    assert result["unplaced"] == ["Mug"]
    assert (result["restocked"], result["damaged"]) == (3, 0)
    assert stock_of(shirt_v) == before + 1
    mug = request.items.get(order_item__product_name="Mug")
    assert mug.good_quantity == 2  # still on the record


# --- two people at once ----------------------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
def test_two_staff_receiving_the_same_request_at_once_move_the_stock_once():
    request, mug_v, _, _ = asked_for([(0, 2)])
    before = stock_of(mug_v)

    def receive(_):
        try:
            return services.receive_goods(ReturnRequest.objects.get(pk=request.pk), lines_for(request, Mug=(2, 0)))
        except services.InvalidTransition:
            return "refused"

    results = run_together(2, receive)

    assert sorted(result if isinstance(result, str) else "received" for result in results) == ["received", "refused"]
    assert stock_of(mug_v) == before + 2  # not +4


# --- the stock service itself ---------------------------------------------------------------------------------------
def test_take_back_stock_puts_good_units_on_the_shelf_and_counts_the_damaged_ones_apart():
    product, variant = stocked(stock=5)
    other_product, other = stocked("Other", stock=5)

    gone = order_services.take_back_stock({variant.pk: 2, other.pk: 1}, {other.pk: 3})

    assert gone == set()
    assert (stock_of(variant), damaged_of(variant)) == (7, 0)
    assert (stock_of(other), damaged_of(other)) == (6, 3)


def test_take_back_stock_ignores_zero_units_and_nothing_at_all():
    _, variant = stocked(stock=5)
    assert order_services.take_back_stock({variant.pk: 0}, {variant.pk: 0}) == set()
    assert order_services.take_back_stock() == set()
    assert (stock_of(variant), damaged_of(variant)) == (5, 0)


def test_take_back_stock_names_the_variants_that_do_not_exist():
    _, variant = stocked(stock=5)
    assert order_services.take_back_stock({variant.pk: 1, 987654: 4}, {987655: 2}) == {987654, 987655}
    assert stock_of(variant) == 6


def test_the_damaged_counter_starts_at_nothing_and_is_not_part_of_what_can_be_bought():
    _, variant = stocked(stock=5)
    assert damaged_of(variant) == 0
    order = make_order(line(variant.product, variant, 5))
    assert Order.objects.get(pk=order.pk).status == "pending"
    assert stock_of(variant) == 0
