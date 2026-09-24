from django.contrib import admin

from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    """A read-only ledger. A payment follows its order: staff move the ORDER (Orders > Mark as delivered ...) and the
    payment changes with it, so the two can not drift apart."""

    list_display = ("order", "method", "status", "amount", "paid_at", "refunded_at", "created_at")
    list_filter = ("status", "method")
    list_select_related = ("order",)
    search_fields = ("order__number", "order__name", "order__phone_number")
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
