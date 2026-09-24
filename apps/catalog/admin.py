from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.forms import BaseInlineFormSet
from django.utils.html import format_html

from . import pricing, services
from .models import Brand, Category, Color, Product, ProductMedia, ProductVariant, Size, Tag


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "parent", "is_active", "is_featured", "is_flash_sale", "is_new_arrival", "is_best_selling")
    list_filter = ("is_active", "is_featured", "is_flash_sale", "is_new_arrival", "is_best_selling")
    list_select_related = ("parent",)
    search_fields = ("name", "slug")
    autocomplete_fields = ("parent",)
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("created_at", "updated_at")


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    search_fields = ("name",)


@admin.register(Color)
class ColorAdmin(admin.ModelAdmin):
    list_display = ("name", "swatch")
    search_fields = ("name",)

    @admin.display(description="Colour")
    def swatch(self, obj):
        return format_html(
            '<span style="display:inline-block;width:1.2em;height:1.2em;vertical-align:middle;'
            'border:1px solid #888;background:{}"></span> {}',
            obj.hex_code,
            obj.hex_code,
        )


@admin.register(Size)
class SizeAdmin(admin.ModelAdmin):
    list_display = ("name", "sort_order")
    list_editable = ("sort_order",)
    search_fields = ("name",)


class ProductVariantFormSet(BaseInlineFormSet):
    """Cross-row rules the database would only reject with a 500 (NULL colour/size defeat the form-level
    unique check): no duplicate colour+size, one default, and every variant of a multi-variant product has options."""

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        forms = [form for form in self.forms if form.cleaned_data and not form.cleaned_data.get("DELETE")]
        seen = set()
        defaults = 0
        for form in forms:
            data = form.cleaned_data
            combination = (data.get("color"), data.get("size"))
            if combination in seen:
                raise ValidationError("Two variants have the same colour and size.")
            seen.add(combination)
            defaults += bool(data.get("is_default"))
            message = pricing.discount_price_error(
                data.get("base_price"), data.get("discount_price"), self.instance.base_price
            )
            if message:
                form.add_error("discount_price", message)
        if defaults > 1:
            raise ValidationError("Only one variant can be the default.")
        if len(forms) > 1 and (None, None) in seen:
            raise ValidationError("When a product has several variants, each one needs a colour or a size.")


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    formset = ProductVariantFormSet
    fields = ("color", "size", "sku", "base_price", "discount_price", "stock_quantity", "is_default", "is_active")
    autocomplete_fields = ("color", "size")
    extra = 0
    min_num = 1
    validate_min = True


class ProductMediaInline(admin.TabularInline):
    model = ProductMedia
    fields = ("file", "preview", "thumbnail", "color", "order")
    readonly_fields = ("preview",)
    autocomplete_fields = ("color",)
    extra = 0

    @admin.display(description="Preview")
    def preview(self, obj):
        if obj.pk and obj.thumbnail:
            return format_html('<img src="{}" alt="" style="height:60px">', obj.thumbnail.url)
        return obj.file_type or ""


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("thumb", "name", "sku", "brand", "price", "stock", "is_active", "is_featured", "created_at")
    list_display_links = ("thumb", "name")
    list_filter = ("is_active", "is_featured", "is_flash_sale", "is_new_arrival", "is_best_selling", "brand")
    search_fields = ("name", "sku", "slug", "variants__sku")
    autocomplete_fields = ("brand", "primary_category")
    filter_horizontal = ("categories", "tags")
    prepopulated_fields = {"slug": ("name",)}
    inlines = (ProductVariantInline, ProductMediaInline)
    actions = ("activate", "deactivate")
    readonly_fields = (
        "total_views",
        "total_orders",
        "total_reviews",
        "avg_rating",
        "qrcode_preview",
        "qrcode_target",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (None, {"fields": ("name", "slug", "sku", "brand", "primary_category", "categories", "tags", "is_active")}),
        ("Pricing", {"fields": ("base_price", "discount_type", "discount_value", "minimum_order_quantity")}),
        ("Descriptions", {"fields": ("short_description", "long_description")}),
        (
            "Details",
            {
                "fields": (
                    "model",
                    "weight",
                    ("dimension_width", "dimension_height", "dimension_depth"),
                    "material",
                    "features",
                    "warranty_information",
                    "shipping_information",
                    "return_policy",
                )
            },
        ),
        ("Shop sections", {"fields": ("is_flash_sale", "is_new_arrival", "is_best_selling", "is_featured")}),
        (
            "Statistics",
            {"fields": ("total_views", "total_orders", "total_reviews", "avg_rating"), "classes": ("collapse",)},
        ),
        ("QR code", {"fields": ("qrcode_preview", "qrcode_target"), "classes": ("collapse",)}),
        ("Dates", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("brand")
            .prefetch_related("media")
            .annotate(stock_total=Sum("variants__stock_quantity"))
        )

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        services.sync_primary_category(form.instance)

    @admin.display(description="")
    def thumb(self, obj):
        image = next((media for media in obj.media.all() if media.thumbnail), None)
        return format_html('<img src="{}" alt="" style="height:40px">', image.thumbnail.url) if image else "-"

    @admin.display(description="Price", ordering="base_price")
    def price(self, obj):
        return obj.base_price if not obj.has_discount else f"{obj.final_price} (was {obj.base_price})"

    @admin.display(description="Stock", ordering="stock_total")
    def stock(self, obj):
        return obj.stock_total or 0

    @admin.display(description="QR code")
    def qrcode_preview(self, obj):
        if obj.pk and obj.qrcode_image:
            return format_html('<img src="{}" alt="QR code" style="height:120px">', obj.qrcode_image.url)
        return "Generated when the product is saved."

    @admin.action(description="Show the selected products in the shop")
    def activate(self, request, queryset):
        self.message_user(request, f"{queryset.update(is_active=True)} product(s) are now visible.")

    @admin.action(description="Hide the selected products from the shop")
    def deactivate(self, request, queryset):
        self.message_user(request, f"{queryset.update(is_active=False)} product(s) are now hidden.")
