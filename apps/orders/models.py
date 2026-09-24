from django.conf import settings
from django.db import models
from django.db.models import F, Q

from apps.addresses.models import Address
from apps.catalog.models import Product, ProductVariant, Timestamped, money_field


class DeliveryCharge(Timestamped):
    """What delivery costs for a shipping type. One row per type (created by a migration; the admin can change the
    amount but neither add nor delete rows). An order snapshots the amount, so editing it never changes old orders."""

    shipping_type = models.CharField(max_length=20, choices=Address.ShippingType.choices, unique=True)
    amount = money_field()

    class Meta:
        ordering = ["id"]
        constraints = [models.CheckConstraint(condition=Q(amount__gte=0), name="deliverycharge_amount_gte_0")]

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

    subtotal = money_field()
    delivery_charge = money_field()
    total = money_field()

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
            models.CheckConstraint(
                condition=Q(total=F("subtotal") + F("delivery_charge")), name="order_total_is_subtotal_plus_delivery"
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
