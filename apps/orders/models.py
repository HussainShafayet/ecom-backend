from django.conf import settings
from django.core.validators import MaxValueValidator
from django.db import models
from django.db.models import F, Q

from apps.addresses.models import Address
from apps.catalog.models import Product, ProductVariant, Timestamped, money_field
from apps.core.money import ZERO


class DeliveryCharge(Timestamped):
    """What delivery costs for a shipping type. One row per type (created by a migration; the admin can change the
    amount but neither add nor delete rows). An order snapshots the amount, so editing it never changes old orders."""

    shipping_type = models.CharField(max_length=20, choices=Address.ShippingType.choices, unique=True)
    amount = money_field()
    # How long delivery takes, in calendar days from the day of the order, for the "Delivery in 2-3 days" the shop shows. Both
    # empty = no promise made (nothing is shown): a shop sets them only once it knows what it can keep.
    min_days = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MaxValueValidator(60)], help_text="The fewest days delivery takes. Empty: no estimate shown."
    )
    max_days = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MaxValueValidator(60)], help_text="The most days delivery takes (the same as the fewest for 'in 2 days')."
    )

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gte=0), name="deliverycharge_amount_gte_0"),
            models.CheckConstraint(
                condition=Q(min_days__isnull=True, max_days__isnull=True)
                | Q(min_days__isnull=False, max_days__isnull=False, min_days__lte=F("max_days")),
                name="deliverycharge_days_both_or_neither_in_order",
                violation_error_message="Give both the fewest and the most days (the most may not be less), or leave both empty.",
            ),
        ]

    def __str__(self):
        return f"{self.get_shipping_type_display()}: {self.amount}"


class OrderSequence(models.Model):
    """The last order number handed out on a day (the counter restarts every day). Locked with
    `select_for_update()` while a number is taken, see `services.next_order_number`."""

    day = models.DateField(primary_key=True)
    last = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.day}: {self.last}"


class Order(Timestamped):
    """A placed order. Contact, address and prices are snapshots: later edits to the catalog, the delivery charges
    or the customer's profile never change it. Created only by `services.place_order`; its status changes only
    through `services.change_status`."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"  # staff checked the order (a phone call, for cash on delivery)
        PAID = "paid", "Paid"
        SHIPPED = "shipped", "Shipped"
        DELIVERED = "delivered", "Delivered"
        RETURNED = "returned", "Returned"  # shipped, but the parcel came back: delivery failed or was refused
        CANCELLED = "cancelled", "Cancelled"
        REFUNDED = "refunded", "Refunded"

    class PaymentMethod(models.TextChoices):
        COD = "cod", "Cash on delivery"  # the only method for now (the payments step adds a Payment model)

    # NULL only inside `place_order`'s transaction: the number is assigned last, so the per-day counter is locked for
    # as short a time as possible. NULLs do not clash in the unique index. A committed order always has a number.
    number = models.CharField(max_length=40, unique=True, null=True, editable=False)
    # Guest orders have no user, and are never linked to an account afterwards, not even one with the same phone.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="orders"
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)

    name = models.CharField(max_length=150)
    email = models.EmailField(blank=True)
    phone_number = models.CharField(max_length=14)

    shipping_type = models.CharField(max_length=20, choices=Address.ShippingType.choices)
    shipping_area = models.CharField(max_length=100, blank=True)  # inside_dhaka only
    shipping_division = models.CharField(max_length=100, blank=True)  # outside_dhaka only
    shipping_district = models.CharField(max_length=100, blank=True)  # outside_dhaka only
    shipping_thana = models.CharField(max_length=100, blank=True)  # outside_dhaka only
    shipping_address = models.CharField(max_length=500)

    payment_method = models.CharField(max_length=10, choices=PaymentMethod.choices, default=PaymentMethod.COD)

    # The coupon used, if any (kept even if the coupon is later deleted, so the order still shows what it saved).
    coupon = models.ForeignKey(
        "coupons.Coupon", null=True, blank=True, on_delete=models.SET_NULL, related_name="orders"
    )
    discount_amount = money_field(default=ZERO, help_text="What the coupon took off. 0 when there was none.")
    subtotal = money_field()
    delivery_charge = money_field()
    total = money_field()
    # What the customer was told when they ordered (the shipping type's `min_days` / `max_days` counted from that day). A snapshot,
    # like the charge: changing the estimate later never changes an order that was already placed. Empty when none was promised.
    expected_from = models.DateField(null=True, blank=True, editable=False)
    expected_to = models.DateField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["user", "-created_at"], name="order_user_newest_idx"),
            models.Index(fields=["status", "-created_at"], name="order_status_newest_idx"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(subtotal__gte=0), name="order_subtotal_gte_0"),
            models.CheckConstraint(condition=Q(delivery_charge__gte=0), name="order_delivery_charge_gte_0"),
            models.CheckConstraint(condition=Q(total__gte=0), name="order_total_gte_0"),
            models.CheckConstraint(condition=Q(discount_amount__gte=0), name="order_discount_amount_gte_0"),
            models.CheckConstraint(condition=Q(discount_amount__lte=F("subtotal")), name="order_discount_amount_lte_subtotal"),
            models.CheckConstraint(
                condition=Q(total=F("subtotal") + F("delivery_charge") - F("discount_amount")),
                name="order_total_is_subtotal_plus_delivery_minus_discount",
            ),
        ]

    def __str__(self):
        return self.number or f"Order #{self.pk}"


class OrderItem(models.Model):
    """One line of an order. The product and the variant are kept only as links (SET_NULL, so deleting catalog
    data never fails or removes an order); what the customer bought is in the snapshot columns."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    variant = models.ForeignKey(ProductVariant, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    product_name = models.CharField(max_length=255)
    variant_label = models.CharField(max_length=150)  # "Red / M", or "Default" for a product without options
    sku = models.CharField("SKU", max_length=100)
    unit_price = money_field(help_text="What the customer paid for one unit.")
    base_price = money_field(help_text="The price of one unit before any discount.")
    quantity = models.PositiveIntegerField()
    line_total = money_field()

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gte=1), name="orderitem_quantity_gte_1"),
            models.CheckConstraint(condition=Q(unit_price__gte=0), name="orderitem_unit_price_gte_0"),
            models.CheckConstraint(condition=Q(base_price__gte=0), name="orderitem_base_price_gte_0"),
            models.CheckConstraint(
                condition=Q(line_total=F("unit_price") * F("quantity")),
                name="orderitem_line_total_is_unit_price_times_quantity",
            ),
        ]

    def __str__(self):
        return f"{self.quantity} x {self.product_name} ({self.variant_label})"


class OrderStatusHistory(models.Model):
    """Every status an order has been in, oldest first. The first row has no `from_status`."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="history")
    from_status = models.CharField(max_length=20, choices=Order.Status.choices, blank=True)
    to_status = models.CharField(max_length=20, choices=Order.Status.choices)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        verbose_name_plural = "order status history"

    def __str__(self):
        return f"{self.order_id}: {self.from_status or 'new'} -> {self.to_status}"


class OrderRequestKey(models.Model):
    """What makes placing an order safe to repeat. A checkout may send an `Idempotency-Key` (one random token per order the customer means to place):
    the first request with that key places the order and leaves a row here; the same key again (a double tap, a retry after a lost answer) finds the row
    and is answered with that order instead of placing a second one. The key counts only for its `owner` (the signed-in customer, or the guest's phone
    number): somebody else's request with the same token is another order, and can not read this one. `fingerprint` is a hash of what was asked for, so
    the same key with a different order is refused instead of silently answered with the first. A request that was refused (out of stock, a bad coupon)
    leaves no row: the customer fixes it and sends the same key again. The row is small and kept with the order."""

    key = models.CharField(max_length=64)
    owner = models.CharField(max_length=40)
    fingerprint = models.CharField(max_length=64)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="request_keys")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["key", "owner"], name="orderrequestkey_one_per_key_and_owner")]

    def __str__(self):
        return f"{self.key} ({self.owner}) -> order #{self.order_id}"
