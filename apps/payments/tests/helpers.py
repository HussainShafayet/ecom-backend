from apps.orders import services as order_services
from apps.orders.models import Order
from apps.orders.tests.helpers import line, make_order, stocked  # noqa: F401  (re-exported for the tests)
from apps.payments.models import Payment


def placed(quantity=2, stock=10, price="500.00", user=None, **overrides):
    """An order for `quantity` mugs. Returns (order, variant)."""
    mug, variant = stocked("Mug", stock=stock, base_price=price)
    return make_order(line(mug, quantity=quantity), user=user, **overrides), variant


def move(order, *statuses, by=None):
    """Walk the order through `statuses` with the real service (which tells payments), like the admin does."""
    for status in statuses:
        order_services.change_status(order, status, by=by)
    order.refresh_from_db()
    return order


def payment_of(order):
    """The order's only payment (fails when there is not exactly one)."""
    return Payment.objects.get(order=order)


Status = Order.Status
