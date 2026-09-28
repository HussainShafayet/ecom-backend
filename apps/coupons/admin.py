from django.contrib import admin

from .models import Coupon


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = ("code", "discount_type", "discount_value", "times_used", "max_redemptions", "is_active", "valid_until")
    list_editable = ("is_active",)
    list_filter = ("discount_type", "is_active")
    search_fields = ("code", "description")
    readonly_fields = ("times_used", "created_at", "updated_at")
    actions = ("activate", "deactivate")

    @admin.action(description="Turn the selected coupons on")
    def activate(self, request, queryset):
        self.message_user(request, f"{queryset.update(is_active=True)} coupon(s) turned on.")

    @admin.action(description="Turn the selected coupons off")
    def deactivate(self, request, queryset):
        self.message_user(request, f"{queryset.update(is_active=False)} coupon(s) turned off.")
