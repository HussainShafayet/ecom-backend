from django.db import models
from django.db.models import Q

from apps.catalog.models import Timestamped, money_field
from apps.orders.models import Order


class Payment(Timestamped):
    """The money side of one order. Created when the order is placed and moved along by the order's status changes
    (see `services.py`); nothing else changes its status. For cash on delivery the courier collects the cash, so the
    payment turns `paid` when the order is delivered."""

    class Method(models.TextChoices):
        COD = "cod", "Cash on delivery"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PAID = "paid", "Paid"
        CANCELLED = "cancelled", "Cancelled"  # never collected
        REFUNDED = "refunded", "Refunded"  # collected, then given back

    # PROTECT: an order with money attached is never deleted by accident.
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="payments")
    method = models.CharField(max_length=10, choices=Method.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    amount = money_field()  # a snapshot of the order total
    paid_at = models.DateTimeField(null=True, blank=True)
    refunded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["status", "-created_at"], name="payment_status_newest_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gte=0), name="payment_amount_gte_0"),
            # A later gateway may retry a payment, so an order can have several rows, but only one alive.
            models.UniqueConstraint(
                fields=["order"],
                condition=Q(status__in=["pending", "paid"]),
                name="payment_one_live_per_order",
            ),
            models.CheckConstraint(
                condition=~Q(status__in=["paid", "refunded"]) | Q(paid_at__isnull=False),
                name="payment_collected_has_paid_at",
            ),
            models.CheckConstraint(
                condition=~Q(status="refunded") | Q(refunded_at__isnull=False),
                name="payment_refunded_has_refunded_at",
            ),
        ]

    def __str__(self):
        return f"{self.order} {self.get_status_display().lower()} ({self.amount})"
