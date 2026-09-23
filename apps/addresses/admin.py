from django.contrib import admin

from .models import Address


@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "title", "shipping_type", "district", "area", "created_at")
    list_filter = ("shipping_type",)
    search_fields = ("user__phone_number", "user__name", "address", "title")
    raw_id_fields = ("user",)
