from django.contrib import admin, messages
from django.db import transaction
from django.utils.html import format_html

from . import services
from .models import Review, ReviewMedia


class ReviewMediaInline(admin.TabularInline):
    model = ReviewMedia
    extra = 0
    can_delete = True  # staff may remove an inappropriate photo
    fields = ("preview", "content_type", "created_at")
    readonly_fields = fields

    @admin.display(description="File")
    def preview(self, media):
        if not media.pk:
            return ""
        if media.is_video:
            return format_html('<a href="{}" target="_blank">video</a>', media.file.url)
        return format_html('<a href="{0}" target="_blank"><img src="{0}" alt="" style="height:60px"></a>', media.file.url)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    """Reviews are written by customers (through the API, after a delivered order). Staff moderate: hide one (untick
    `is_approved`), delete one, remove a photo. The product's rating follows on its own."""

    list_display = ("product", "user", "rating", "short_comment", "is_approved", "created_at")
    list_display_links = ("product", "short_comment")
    list_filter = ("is_approved", "rating")
    list_select_related = ("product", "user")
    search_fields = ("product__name", "product__sku", "user__name", "user__phone_number", "comment")
    date_hierarchy = "created_at"
    readonly_fields = ("product", "user", "rating", "comment", "created_at", "updated_at")
    fields = (*readonly_fields, "is_approved")
    inlines = (ReviewMediaInline,)
    actions = ("show", "hide")

    @admin.display(description="Comment")
    def short_comment(self, review):
        return review.comment if len(review.comment) <= 60 else f"{review.comment[:57]}..."

    def has_add_permission(self, request):
        return False

    def _set_approved(self, request, queryset, approved):
        with transaction.atomic():
            product_ids = sorted(set(queryset.values_list("product_id", flat=True)))
            changed = queryset.update(is_approved=approved)  # a bulk update sends no signals: recount by hand
            for product_id in product_ids:
                services.refresh_product_rating(product_id)
        self.message_user(request, f"{changed} review(s) {'shown' if approved else 'hidden'}.", messages.SUCCESS)

    @admin.action(description="Show the selected reviews")
    def show(self, request, queryset):
        self._set_approved(request, queryset, True)

    @admin.action(description="Hide the selected reviews")
    def hide(self, request, queryset):
        self._set_approved(request, queryset, False)
