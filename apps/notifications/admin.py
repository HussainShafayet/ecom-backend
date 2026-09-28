from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse

from .models import NotificationSettings


@admin.register(NotificationSettings)
class NotificationSettingsAdmin(admin.ModelAdmin):
    """One row: the menu entry opens it directly (a list of one would only be a click in the way)."""

    def changelist_view(self, request, extra_context=None):
        return redirect(reverse("admin:notifications_notificationsettings_change", args=[NotificationSettings.load().pk]))

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
