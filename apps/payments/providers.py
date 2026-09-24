"""How each payment method behaves. A provider answers two questions: what record does a new order get, and what
happens to that record when the order's status changes. Only cash on delivery exists (the frontend offers nothing
else); a gateway is a new subclass registered in `PROVIDERS`, with its callbacks added then.
"""
from apps.orders.models import Order

from .models import Payment

OrderStatus = Order.Status
PaymentStatus = Payment.Status


class PaymentProvider:
    method = None

    def create_payment(self, order):
        """The payment record of a freshly placed order."""
        raise NotImplementedError

    def status_after(self, payment, new_order_status):
        """The payment status the order's new status leads to, or None when the payment is unaffected."""
        raise NotImplementedError


class CashOnDelivery(PaymentProvider):
    """Nothing is collected until the courier hands the parcel over: delivered (or a staff member marking the order
    paid) is when the cash arrives. An order that ends without delivery cancels the payment; cash that was already
    collected is refunded (by hand: the shop gives the money back, the system only records it)."""

    method = Payment.Method.COD

    # order status -> {payment status now: payment status after}
    EFFECTS = {
        OrderStatus.PAID: {PaymentStatus.PENDING: PaymentStatus.PAID},
        OrderStatus.DELIVERED: {PaymentStatus.PENDING: PaymentStatus.PAID},
        OrderStatus.CANCELLED: {
            PaymentStatus.PENDING: PaymentStatus.CANCELLED,
            PaymentStatus.PAID: PaymentStatus.REFUNDED,
        },
        # A parcel that came back was never paid for at the door; cash collected earlier (staff marked the order
        # paid) is given back. `confirmed` and `shipped` change nothing: they are not in this table.
        OrderStatus.RETURNED: {
            PaymentStatus.PENDING: PaymentStatus.CANCELLED,
            PaymentStatus.PAID: PaymentStatus.REFUNDED,
        },
        OrderStatus.REFUNDED: {
            PaymentStatus.PENDING: PaymentStatus.CANCELLED,
            PaymentStatus.PAID: PaymentStatus.REFUNDED,
        },
    }

    def create_payment(self, order):
        return Payment.objects.create(
            order=order, method=self.method, status=PaymentStatus.PENDING, amount=order.total
        )

    def status_after(self, payment, new_order_status):
        return self.EFFECTS.get(new_order_status, {}).get(payment.status)


PROVIDERS = {provider.method: provider for provider in (CashOnDelivery(),)}


def provider_for(method):
    try:
        return PROVIDERS[method]
    except KeyError:
        raise LookupError(f"There is no payment provider for {method!r}.") from None
