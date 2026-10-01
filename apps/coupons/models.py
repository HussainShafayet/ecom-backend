"""A promo code a customer types at checkout. Redeeming one is `services.apply_coupon_to_order` (called only from
`orders.services.place_order`, inside its transaction); a cancelled order's use is given back by
`services.release_coupon_usage` (called from `orders.services.change_status`), the same shape as stock restocking."""
from django.db import models
from django.db.models import CheckConstraint, F, Q

from apps.catalog.models import DiscountType, Timestamped, money_field


class Coupon(Timestamped):
    code = models.CharField(max_length=40, unique=True, help_text="What the customer types. Stored upper case.")
    description = models.CharField(max_length=200, blank=True, help_text="Staff-only note; never shown to a customer.")
    discount_type = models.CharField(max_length=20, choices=DiscountType.choices)
    discount_value = money_field(help_text="A percentage (0-100) or a fixed amount, depending on the type above.")
    min_order_amount = money_field(null=True, blank=True, help_text="The subtotal must be at least this. Empty: no minimum.")
    max_discount_amount = money_field(
        null=True, blank=True, help_text="Caps how much is taken off, however big the order. Empty: no cap."
    )
    max_redemptions = models.PositiveIntegerField(null=True, blank=True, help_text="Total uses allowed. Empty: unlimited.")
    max_redemptions_per_customer = models.PositiveIntegerField(
        null=True, blank=True, help_text="Uses allowed per phone number. Empty: unlimited."
    )
    times_used = models.PositiveIntegerField(default=0, editable=False, help_text="Moved only by code, like a product's order count.")
    valid_from = models.DateTimeField(null=True, blank=True, help_text="Empty: usable from the moment it is saved.")
    valid_until = models.DateTimeField(null=True, blank=True, help_text="Empty: never expires on its own.")
    is_active = models.BooleanField(default=True, help_text="Untick to turn it off immediately, without waiting for an expiry date.")
    show_at_checkout = models.BooleanField(
        default=False,
        help_text="Suggest this coupon to customers at checkout, so they do not need to know the code. "
        "Leave it off for secret codes (influencers, a sorry-for-the-delay code): it still works when typed.",
    )
    public_title = models.CharField(
        max_length=60,
        blank=True,
        help_text='What the customer reads on the offer, e.g. "25% off your first order". Needed to show the coupon at checkout.',
    )

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            CheckConstraint(condition=Q(discount_value__gt=0), name="coupon_discount_value_gt_0"),
            CheckConstraint(
                condition=~Q(discount_type=DiscountType.PERCENTAGE) | Q(discount_value__lte=100),
                name="coupon_percentage_value_lte_100",
            ),
            CheckConstraint(
                condition=Q(min_order_amount__isnull=True) | Q(min_order_amount__gte=0),
                name="coupon_min_order_amount_gte_0",
            ),
            CheckConstraint(
                condition=Q(max_discount_amount__isnull=True) | Q(max_discount_amount__gt=0),
                name="coupon_max_discount_amount_gt_0",
            ),
            CheckConstraint(
                condition=Q(valid_from__isnull=True) | Q(valid_until__isnull=True) | Q(valid_until__gt=F("valid_from")),
                name="coupon_valid_until_after_valid_from",
            ),
            CheckConstraint(
                condition=Q(show_at_checkout=False) | ~Q(public_title=""),
                name="coupon_shown_at_checkout_needs_a_title",
                violation_error_message="Write the title customers will see before showing this coupon at checkout.",
            ),
        ]

    def __str__(self):
        return self.code

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        self.public_title = self.public_title.strip()
        super().save(*args, **kwargs)
