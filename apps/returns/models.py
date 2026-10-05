"""Return requests: a customer asks to send delivered goods back, staff decide.

A request is NOT an order status. `orders.state` knows the whole order only (`delivered -> refunded`), while a customer usually sends back
one line of three: the request lives next to the order and never changes it. The shop works in cash on delivery, so the money is paid back
by hand: a completed request only records what was paid back. What the request DOES change is the inventory: when the goods are received
(`services.receive_goods`) the good units go back on the shelf and the damaged ones are only counted (`ProductVariant.damaged_quantity`).

Money of one request (all snapshots, so a later change of the delivery charges or the policy never rewrites an old request):
  goods_amount   the price of the returned lines, less their share of the order's coupon
  courier_cost   what the courier charges to carry the goods back: the order's own delivery charge
  return_charge  what the customer pays of it, taken off the refund (0 when the shop was at fault, or the shop waives it)
  refund_amount  what the shop pays back: goods_amount - return_charge, which staff may still change
  shop cost      courier_cost - return_charge: what the shop itself pays for the courier (it comes out of the shop's profit)
"""
from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q

from apps.catalog.models import Timestamped, money_field
from apps.core.money import ZERO
from apps.orders.models import Order, OrderItem

SINGLETON_ID = 1


class ReturnSettings(models.Model):
    """The shop's return policy: one row, edited in the admin (Returns > Return settings). Without a row the defaults
    below apply, so a shop that never opens this page takes returns for 7 days and charges the delivery charge for them."""

    enabled = models.BooleanField(default=True, help_text="Untick to stop taking new return requests (existing ones stay).")
    window_days = models.PositiveSmallIntegerField(
        default=7,
        validators=[MinValueValidator(1), MaxValueValidator(90)],
        help_text="How many days after delivery a customer may ask to return something.",
    )
    charge_return_delivery = models.BooleanField(
        default=True,
        help_text="The customer pays the delivery charge of sending the goods back (it is taken off the refund), unless the shop was at "
        "fault: damaged, wrong item, not as described. Untick and every return is free; the shop pays the courier. Staff can still waive the "
        "charge of one request.",
    )

    class Meta:
        verbose_name = verbose_name_plural = "return settings"
        constraints = [models.CheckConstraint(condition=Q(id=SINGLETON_ID), name="returns_one_settings_row")]

    def __str__(self):
        return "Return settings"

    @classmethod
    def load(cls):
        """The row, created with the defaults if the shop has none yet (the admin uses this)."""
        return cls.objects.get_or_create(pk=SINGLETON_ID)[0]

    @classmethod
    def current(cls):
        """The row, or an unsaved one with the defaults: reading the policy never writes."""
        return cls.objects.filter(pk=SINGLETON_ID).first() or cls()

    def save(self, *args, **kwargs):
        self.pk = SINGLETON_ID
        super().save(*args, **kwargs)


class ReturnRequest(Timestamped):
    """One customer's request to return some lines of a delivered order. Created only by `services.request_return`;
    its status changes only through `services.change_status` / `staff_update` / `receive_goods` (the moves are in `state.py`)."""

    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested"  # waiting for the shop
        APPROVED = "approved", "Approved"  # the shop agreed: the goods are to be sent back
        RECEIVED = "received", "Received"  # the goods are back and entered: the stock is updated, the refund is being prepared
        REJECTED = "rejected", "Rejected"
        COMPLETED = "completed", "Completed"  # the money was paid back
        CANCELLED = "cancelled", "Cancelled"  # the customer (or the shop, after approving) called it off

    class Reason(models.TextChoices):
        DAMAGED = "damaged", "It arrived damaged"
        WRONG_ITEM = "wrong_item", "I got the wrong item"
        NOT_AS_DESCRIBED = "not_as_described", "It is not as described"
        SIZE_FIT = "size_fit", "The size or fit is wrong"
        CHANGED_MIND = "changed_mind", "I changed my mind"
        OTHER = "other", "Something else"

    # The shop was at fault: sending these back is free for the customer (the shop pays the courier)
    FREE_REASONS = (Reason.DAMAGED, Reason.WRONG_ITEM, Reason.NOT_AS_DESCRIBED)

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="return_requests")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.REQUESTED)
    reason = models.CharField(max_length=30, choices=Reason.choices)
    details = models.CharField(max_length=500, blank=True, help_text="What the customer wrote (required for 'Something else').")
    response = models.CharField(
        max_length=500,
        blank=True,
        help_text="Your message to the customer, shown on their order: how to send the goods back, or why it was refused.",
    )
    goods_amount = money_field(default=ZERO, help_text="The price of the returned lines, less their share of the order's coupon.")
    courier_cost = money_field(default=ZERO, help_text="What the courier charges to carry the goods back (the order's delivery charge).")
    return_charge = money_field(
        default=ZERO,
        help_text="What the customer pays of the courier cost, taken off the refund. 0 = free return: the shop pays the courier "
        "(that comes out of its profit). Worked out from the policy when the request is made; change it to waive it.",
    )
    refund_amount = money_field(
        help_text="What is paid back: the goods less the return charge. Changes by itself when you change the charge; type another "
        "figure to pay back more or less."
    )
    received_at = models.DateTimeField(null=True, blank=True, editable=False)
    completed_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["status", "-created_at"], name="returnreq_status_newest_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(goods_amount__gte=0), name="returnreq_goods_amount_gte_0"),
            models.CheckConstraint(condition=Q(courier_cost__gte=0), name="returnreq_courier_cost_gte_0"),
            models.CheckConstraint(condition=Q(return_charge__gte=0), name="returnreq_return_charge_gte_0"),
            models.CheckConstraint(condition=Q(refund_amount__gte=0), name="returnreq_refund_amount_gte_0"),
        ]

    def __str__(self):
        return f"Return #{self.pk} of {self.order.number or self.order_id}"

    @property
    def shop_cost(self):
        """What the shop pays the courier out of its own pocket: the part of the courier cost the customer does not pay."""
        return max(self.courier_cost - self.return_charge, Decimal("0.00"))


class ReturnItem(models.Model):
    """A line of the order that is to come back, and how many units of it. When the goods are received, `good_quantity` units went back on
    the shelf and `damaged_quantity` were counted as damaged; what is neither did not come back."""

    request = models.ForeignKey(ReturnRequest, on_delete=models.CASCADE, related_name="items")
    order_item = models.ForeignKey(OrderItem, on_delete=models.CASCADE, related_name="+")
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)], help_text="Units the customer asked to return.")
    good_quantity = models.PositiveIntegerField(default=0, help_text="Units that came back fine: back on the shelf.")
    damaged_quantity = models.PositiveIntegerField(default=0, help_text="Units that came back damaged: not sellable, only counted.")

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gte=1), name="returnitem_quantity_gte_1"),
            models.CheckConstraint(
                condition=Q(quantity__gte=F("good_quantity") + F("damaged_quantity")),
                name="returnitem_received_not_more_than_asked",
            ),
            models.UniqueConstraint(fields=["request", "order_item"], name="returnitem_one_line_once_per_request"),
        ]

    def __str__(self):
        return f"{self.quantity} x {self.order_item.product_name}"
