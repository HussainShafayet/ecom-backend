from django import forms
from django.contrib import admin, messages

from . import services, state
from .models import DeliveryCharge, Order, OrderItem, OrderStatusHistory


class OrderStatusForm(forms.ModelForm):
    """The one thing staff may edit on an order is its status, and only to a status the flow allows (`state.py`)."""

    class Meta:
        model = Order
        fields = ("status",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current = self.instance.status
        offered = {current, *state.allowed_next(current)}
        self.fields["status"].choices = [(value, label) for value, label in Order.Status.choices if value in offered]


class ReadOnlyInline(admin.TabularInline):
    extra = 0
    can_delete = False

    def get_readonly_fields(self, request, obj=None):
        return self.fields

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class OrderItemInline(ReadOnlyInline):
    model = OrderItem
    fields = ("product_name", "variant_label", "sku", "unit_price", "base_price", "quantity", "line_total")


class OrderStatusHistoryInline(ReadOnlyInline):
    model = OrderStatusHistory
    fields = ("created_at", "from_status", "to_status", "changed_by", "note")
    verbose_name_plural = "status history"


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    """Orders are made by customers at checkout: staff can neither add nor delete one, and everything is read-only
    but the status. A status changes only through `services.change_status`, from the form and from the actions."""

    form = OrderStatusForm
    list_display = ("number", "created_at", "name", "phone_number", "status", "total")
    list_filter = ("status", "shipping_type", "payment_method", "created_at")
    search_fields = ("number", "name", "phone_number", "email")
    fieldsets = (
        (None, {"fields": ("number", "status", "user", "created_at", "updated_at")}),
        ("Customer", {"fields": ("name", "phone_number", "email")}),
        (
            "Shipping",
            {
                "fields": (
                    "shipping_type",
                    "shipping_area",
                    "shipping_division",
                    "shipping_district",
                    "shipping_thana",
                    "shipping_address",
                )
            },
        ),
        ("Payment", {"fields": ("payment_method", "subtotal", "delivery_charge", "total")}),
    )
    readonly_fields = (
        "number",
        "user",
        "created_at",
        "updated_at",
        "name",
        "phone_number",
        "email",
        "shipping_type",
        "shipping_area",
        "shipping_division",
        "shipping_district",
        "shipping_thana",
        "shipping_address",
        "payment_method",
        "subtotal",
        "delivery_charge",
        "total",
    )
    inlines = (OrderItemInline, OrderStatusHistoryInline)
    actions = ("mark_confirmed", "mark_paid", "mark_shipped", "mark_delivered", "mark_returned", "cancel_and_restock")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        new_status = obj.status
        obj.status = form.initial["status"]  # undo the form's in-memory change: the service is what changes it
        if new_status == obj.status:
            return
        try:
            services.change_status(obj, new_status, by=request.user, note="Changed in the admin.")
        except services.InvalidTransition as exc:  # somebody else moved the order after this page was opened
            self.message_user(request, f"{obj.number}: {exc} Reload the page.", messages.ERROR)

    def _change_all(self, request, queryset, new_status, note, done):
        changed, failures = 0, []
        for order in queryset.order_by("pk"):
            try:
                services.change_status(order, new_status, by=request.user, note=note)
                changed += 1
            except services.InvalidTransition as exc:
                failures.append(f"{order.number}: {exc}")
        if changed:
            self.message_user(request, f"{changed} order(s) {done}.", messages.SUCCESS)
        for failure in failures:
            self.message_user(request, failure, messages.ERROR)

    @admin.action(description="Mark as confirmed", permissions=["change"])
    def mark_confirmed(self, request, queryset):
        self._change_all(request, queryset, Order.Status.CONFIRMED, "Marked as confirmed.", "marked as confirmed")

    @admin.action(description="Mark as paid", permissions=["change"])
    def mark_paid(self, request, queryset):
        self._change_all(request, queryset, Order.Status.PAID, "Marked as paid.", "marked as paid")

    @admin.action(description="Mark as shipped", permissions=["change"])
    def mark_shipped(self, request, queryset):
        self._change_all(request, queryset, Order.Status.SHIPPED, "Marked as shipped.", "marked as shipped")

    @admin.action(description="Mark as delivered", permissions=["change"])
    def mark_delivered(self, request, queryset):
        self._change_all(request, queryset, Order.Status.DELIVERED, "Marked as delivered.", "marked as delivered")

    @admin.action(description="Mark as returned (parcel came back) and restock", permissions=["change"])
    def mark_returned(self, request, queryset):
        self._change_all(
            request,
            queryset,
            Order.Status.RETURNED,
            "Returned: delivery failed or was refused.",
            "marked as returned and put back in stock",
        )

    @admin.action(description="Cancel and restock", permissions=["change"])
    def cancel_and_restock(self, request, queryset):
        self._change_all(
            request, queryset, Order.Status.CANCELLED, "Cancelled in the admin.", "cancelled and put back in stock"
        )


@admin.register(DeliveryCharge)
class DeliveryChargeAdmin(admin.ModelAdmin):
    """One row per shipping type (a migration creates them): staff change the amount, nothing else. Orders keep the
    amount they were placed with."""

    list_display = ("shipping_type", "amount", "updated_at")
    fields = ("shipping_type", "amount", "updated_at")
    readonly_fields = ("shipping_type", "updated_at")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
