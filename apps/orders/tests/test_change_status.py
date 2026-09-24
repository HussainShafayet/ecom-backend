import itertools

import pytest

from apps.accounts.tests.helpers import verified_user
from apps.catalog.models import Product
from apps.orders import services
from apps.orders.models import Order, OrderStatusHistory
from apps.orders.tests.helpers import line, make_order, orders_of, stock_of, stocked, with_options
from apps.orders.tests.test_state import ALL, ALLOWED

pytestmark = pytest.mark.django_db

Status = Order.Status


class Shop:
    """A mug and a shirt in two sizes, and an order for 2 mugs, 3 small and 1 medium shirt."""

    def __init__(self):
        self.mug, self.mug_variant = stocked("Mug", stock=10)
        self.shirt, (self.small, self.medium) = with_options("Shirt", stocks=(10, 10))
        self.order = make_order(
            line(self.mug, self.mug_variant, 2), line(self.shirt, self.small, 3), line(self.shirt, self.medium, 1)
        )

    def stock(self):
        return (stock_of(self.mug_variant), stock_of(self.small), stock_of(self.medium))

    def sold(self):
        return (orders_of(self.mug), orders_of(self.shirt))

    def move(self, status):
        """Put the order in `status` directly (as if it had got there), without touching stock or history."""
        Order.objects.filter(pk=self.order.pk).update(status=status)
        self.order.refresh_from_db()


@pytest.fixture
def shop():
    shop = Shop()
    assert shop.stock() == (8, 7, 9) and shop.sold() == (1, 1)
    return shop


def history(order):
    return [(row.from_status, row.to_status) for row in order.history.all()]


# --- the map is enforced --------------------------------------------------------------------------------------
@pytest.mark.parametrize("old, new", sorted(ALLOWED))
def test_every_allowed_transition_works_and_writes_a_history_row(shop, old, new):
    shop.move(old)
    staff = verified_user("+8801700000001")

    result = services.change_status(shop.order, new, by=staff, note="because")

    assert result is shop.order and shop.order.status == new  # the caller's copy is up to date
    assert Order.objects.get(pk=shop.order.pk).status == new
    row = shop.order.history.last()
    assert (row.from_status, row.to_status, row.changed_by, row.note) == (old, new, staff, "because")
    assert shop.order.history.count() == 2  # the row written when it was placed, and this one


FORBIDDEN = [(old, new) for old, new in itertools.product(ALL, ALL) if (old.value, new.value) not in ALLOWED]


@pytest.mark.parametrize("old, new", FORBIDDEN)
def test_every_forbidden_transition_is_refused_and_changes_nothing(shop, old, new):
    shop.move(old)
    stock, sold = shop.stock(), shop.sold()

    with pytest.raises(services.InvalidTransition) as raised:
        services.change_status(shop.order, new)

    assert (raised.value.old, raised.value.new) == (old, new)
    assert Order.objects.get(pk=shop.order.pk).status == old
    assert shop.order.history.count() == 1
    assert (shop.stock(), shop.sold()) == (stock, sold)


def test_the_refusal_reads_as_a_sentence_and_is_a_400(shop):
    shop.move("shipped")
    with pytest.raises(services.InvalidTransition) as raised:
        services.change_status(shop.order, "pending")
    assert str(raised.value.detail) == "A shipped order can not become pending."
    assert raised.value.status_code == 400


def test_an_unknown_status_is_refused(shop):
    with pytest.raises(services.InvalidTransition):
        services.change_status(shop.order, "lost")
    assert Order.objects.get(pk=shop.order.pk).status == "pending"


def test_the_status_is_read_again_under_the_lock_not_taken_from_the_callers_copy(shop):
    stale = Order.objects.get(pk=shop.order.pk)  # still says pending
    services.change_status(shop.order, Status.CANCELLED)

    with pytest.raises(services.InvalidTransition):
        services.change_status(stale, Status.CANCELLED)

    assert shop.stock() == (10, 10, 10)  # given back once, not twice


def test_the_whole_life_of_an_order_is_in_its_history(shop):
    for status in (Status.PAID, Status.SHIPPED, Status.DELIVERED):
        services.change_status(shop.order, status)
    assert history(shop.order) == [
        ("", "pending"),
        ("pending", "paid"),
        ("paid", "shipped"),
        ("shipped", "delivered"),
    ]


def test_changed_by_and_note_are_optional(shop):
    services.change_status(shop.order, Status.PAID)
    row = shop.order.history.last()
    assert row.changed_by is None and row.note == ""


def test_the_change_moves_the_updated_at_stamp(shop):
    before = Order.objects.get(pk=shop.order.pk).updated_at
    services.change_status(shop.order, Status.PAID)
    assert Order.objects.get(pk=shop.order.pk).updated_at > before


# --- restocking -----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("old", [Status.PENDING, Status.PAID, Status.SHIPPED])
def test_cancelling_puts_the_goods_back_and_takes_the_sale_off_the_products(shop, old):
    shop.move(old)
    services.change_status(shop.order, Status.CANCELLED)
    assert shop.stock() == (10, 10, 10)
    assert shop.sold() == (0, 0)


def test_refunding_a_paid_order_that_never_left_puts_the_goods_back(shop):
    shop.move(Status.PAID)
    services.change_status(shop.order, Status.REFUNDED)
    assert shop.stock() == (10, 10, 10)
    assert shop.sold() == (0, 0)


def test_refunding_a_delivered_order_does_not_restock(shop):
    """The goods already left. Whether they come back sellable is for a person to decide (edit the stock)."""
    shop.move(Status.DELIVERED)
    services.change_status(shop.order, Status.REFUNDED)
    assert shop.stock() == (8, 7, 9)
    assert shop.sold() == (1, 1)


@pytest.mark.parametrize(
    "old, new",
    [("pending", "paid"), ("pending", "shipped"), ("paid", "shipped"), ("shipped", "delivered")],
)
def test_moving_forward_never_touches_the_stock(shop, old, new):
    shop.move(old)
    services.change_status(shop.order, new)
    assert shop.stock() == (8, 7, 9) and shop.sold() == (1, 1)


def test_the_full_path_to_a_refund_keeps_the_stock_taken(shop):
    for status in (Status.PAID, Status.SHIPPED, Status.DELIVERED, Status.REFUNDED):
        services.change_status(shop.order, status)
    assert shop.stock() == (8, 7, 9)


def test_total_orders_goes_down_once_per_product_not_per_variant_or_unit(shop):
    services.change_status(shop.order, Status.CANCELLED)
    assert shop.sold() == (0, 0)  # the shirt had two variants and 4 units in the order


def test_total_orders_never_goes_below_zero(shop):
    Product.objects.filter(pk=shop.mug.pk).update(total_orders=0)  # e.g. edited by hand
    services.change_status(shop.order, Status.CANCELLED)
    assert orders_of(shop.mug) == 0
    assert orders_of(shop.shirt) == 0


def test_only_this_orders_share_comes_back():
    mug, variant = stocked("Mug", stock=10)
    first = make_order(line(mug, variant, 2))
    make_order(line(mug, variant, 3))
    services.change_status(first, Status.CANCELLED)
    assert stock_of(variant) == 10 - 3
    assert orders_of(mug) == 1


def test_a_second_cancel_is_refused_so_the_goods_are_never_returned_twice(shop):
    services.change_status(shop.order, Status.CANCELLED)
    with pytest.raises(services.InvalidTransition):
        services.change_status(shop.order, Status.CANCELLED)
    assert shop.stock() == (10, 10, 10)


def test_lines_whose_product_was_deleted_have_nothing_to_go_back_to(shop):
    shop.mug.delete()  # its variant goes too, the order line keeps its snapshot
    services.change_status(shop.order, Status.CANCELLED)
    assert (stock_of(shop.small), stock_of(shop.medium)) == (10, 10)
    assert orders_of(shop.shirt) == 0
    assert Order.objects.get(pk=shop.order.pk).status == "cancelled"


def test_a_line_whose_variant_was_deleted_but_not_its_product_is_skipped(shop):
    shop.small.delete()
    services.change_status(shop.order, Status.CANCELLED)
    assert (stock_of(shop.mug_variant), stock_of(shop.medium)) == (10, 10)
    assert shop.sold() == (0, 0)


def test_a_failure_while_restocking_leaves_the_status_and_history_alone(shop, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("database went away")

    monkeypatch.setattr(services, "_shift_stock", boom)
    with pytest.raises(RuntimeError):
        services.change_status(shop.order, Status.CANCELLED)
    assert Order.objects.get(pk=shop.order.pk).status == "pending"
    assert OrderStatusHistory.objects.filter(order=shop.order).count() == 1
    assert shop.order.status == "pending"  # and the caller's copy did not move either
