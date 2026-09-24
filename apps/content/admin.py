from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.forms import BaseInlineFormSet
from django.utils.html import format_html

from .models import BANNERS, ContentItem, MediaType, PageContent, Placement


class ContentItemFormSet(BaseInlineFormSet):
    """Two active banners on one side of a page can not both be shown. The database refuses that too, but only
    with a 500; this says it in the form."""

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        seen = set()
        for form in self.forms:
            data = form.cleaned_data
            if not data or data.get("DELETE") or not data.get("is_active"):
                continue
            placement = data.get("placement")
            if placement in BANNERS:
                if placement in seen:
                    raise ValidationError(
                        f"Only one active {Placement(placement).label.lower()} is allowed. "
                        "Untick 'Is active' on the other one."
                    )
                seen.add(placement)


class ContentItemInline(admin.StackedInline):
    model = ContentItem
    formset = ContentItemFormSet
    fields = (
        ("placement", "order", "is_active"),
        ("link_type", "product", "category", "external_link"),
        ("media", "preview"),
        "caption",
    )
    readonly_fields = ("preview",)
    autocomplete_fields = ("product", "category")
    extra = 0

    @admin.display(description="Preview")
    def preview(self, obj):
        if not (obj.pk and obj.media):
            return ""
        if obj.media_type == MediaType.VIDEO:
            return format_html('<video src="{}" style="height:80px" controls muted></video>', obj.media.url)
        return format_html('<img src="{}" alt="" style="height:80px">', obj.media.url)


@admin.register(PageContent)
class PageContentAdmin(admin.ModelAdmin):
    """The six pages are fixed (created by a migration); an admin only fills them in."""

    list_display = ("__str__", "active_items")
    readonly_fields = ("page", "created_at", "updated_at")
    inlines = (ContentItemInline,)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(active=Count("items", filter=Q(items__is_active=True)))

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Active slides and banners", ordering="active")
    def active_items(self, obj):
        return obj.active
