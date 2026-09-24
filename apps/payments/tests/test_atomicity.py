import pytest

from apps.accounts.tests.helpers import verified_user
from apps.cart.models import CartItem
from apps.orders import services as order_services
from apps.orders.models import Order
from apps.orders.tests.helpers import line, make_order, stock_of, stocked
from apps.payments import services
from apps.payments.models import Payment
from apps.payments.tests.helpers import payment_of, placed

pytestmark = pytest.mark.django_db


def boom(*args, **kwargs):
    raise RuntimeError("the payment side failed")


def test_a_payment_failure_takes_the_status_change_back_with_it(monkeypatch):
    order, variant = placed(quantity=2, stock=10)
    monkeypatch.setattr(services, "handle_order_status_changed", boom)

    with pytest.raises(RuntimeError):
        order_services.change_status(order, Order.Status.CANCELLED)

    order.refresh_from_db()
    assert order.status == "pending"
    assert order.history.count() == 1  # only "Order placed."
    assert stock_of(variant) == 8  # the restock was rolled back too
    assert payment_of(order).status == "pending"


def test_a_payment_failure_takes_the_whole_order_back_with_it(monkeypatch):
    user = verified_user()
    mug, variant = stocked("Mug", stock=5)
    CartItem.objects.create(user=user, variant=variant, quantity=2)
    monkeypatch.setattr(services, "open_payment", boom)

    with pytest.raises(RuntimeError):
        make_order(line(mug, quantity=2), user=user)

    assert Order.objects.count() == 0 and Payment.objects.count() == 0
    assert stock_of(variant) == 5
    assert list(CartItem.objects.filter(user=user).values_list("quantity", flat=True)) == [2]


def test_the_receivers_are_connected_once():
    """Two connections would open two payments for one order (the constraint would then refuse the order)."""
    order, _ = placed()
    assert Payment.objects.filter(order=order).count() == 1
    order_services.change_status(order, Order.Status.SHIPPED)
    order_services.change_status(order, Order.Status.DELIVERED)
    assert Payment.objects.filter(order=order).count() == 1
