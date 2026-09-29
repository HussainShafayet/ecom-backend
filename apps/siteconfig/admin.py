import csv

from django.contrib import admin
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

from .models import ContactMessage, FaqItem, NewsletterSubscriber, SiteSettings, SocialLink, StaticPage, TrustBadge


class SocialLinkInline(admin.TabularInline):
    model = SocialLink
    extra = 0


class TrustBadgeInline(admin.TabularInline):
    model = TrustBadge
    extra = 0


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    """One row: the menu entry opens it directly (a list of one would only be a click in the way)."""

    fieldsets = (
        ("Shop", {"fields": ("site_name", "tagline", "logo")}),
        ("Announcement bar", {"fields": ("announcement_enabled", "announcement_text", "announcement_link")}),
        ("Contact details", {"fields": ("contact_email", "contact_phone", "contact_address", "opening_hours", "map_embed_url")}),
    )
    inlines = (SocialLinkInline, TrustBadgeInline)

    def changelist_view(self, request, extra_context=None):
        return redirect(reverse("admin:siteconfig_sitesettings_change", args=[SiteSettings.load().pk]))

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(StaticPage)
class StaticPageAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "is_published", "footer_group", "order", "updated_at")
    list_editable = ("is_published", "footer_group", "order")
    list_filter = ("is_published", "footer_group")
    search_fields = ("title", "slug")
    prepopulated_fields = {"slug": ("title",)}


@admin.register(FaqItem)
class FaqItemAdmin(admin.ModelAdmin):
    list_display = ("question", "category", "order", "is_active")
    list_editable = ("order", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("question", "answer")


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    """The staff read these and tick "handled"; what the visitor wrote is not editable."""

    list_display = ("created_at", "name", "email", "subject", "is_handled")
    list_filter = ("is_handled", "created_at")
    search_fields = ("name", "email", "subject", "message")
    readonly_fields = ("created_at",)
    fields = (*readonly_fields, "is_handled")
    actions = ("mark_handled", "mark_unhandled")

    def has_add_permission(self, request):
        return False

    @admin.action(description="Mark the selected messages as handled")
    def mark_handled(self, request, queryset):
        self.message_user(request, f"{queryset.update(is_handled=True)} message(s) marked as handled.")

    @admin.action(description="Mark the selected messages as not handled")
    def mark_unhandled(self, request, queryset):
        self.message_user(request, f"{queryset.update(is_handled=False)} message(s) marked as not handled.")


@admin.register(NewsletterSubscriber)
class NewsletterSubscriberAdmin(admin.ModelAdmin):
    list_display = ("email", "is_active", "subscribed_at")
    list_filter = ("is_active", "subscribed_at")
    search_fields = ("email",)
    actions = ("export_csv", "deactivate", "activate")

    @admin.action(description="Download the selected addresses as CSV")
    def export_csv(self, request, queryset):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="newsletter-subscribers.csv"'
        writer = csv.writer(response)
        writer.writerow(["email", "active", "subscribed_at"])
        for row in queryset.order_by("id"):
            writer.writerow([row.email, "yes" if row.is_active else "no", row.subscribed_at.isoformat()])
        return response

    @admin.action(description="Stop sending to the selected addresses")
    def deactivate(self, request, queryset):
        self.message_user(request, f"{queryset.update(is_active=False)} address(es) deactivated.")

    @admin.action(description="Send to the selected addresses again")
    def activate(self, request, queryset):
        self.message_user(request, f"{queryset.update(is_active=True)} address(es) activated.")
