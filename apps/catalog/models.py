from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models, transaction
from django.db.models import F, Q
from django.db.models.functions import Lower
from django.utils.text import slugify

from apps.core.models import FileCleanupModel
from apps.core.sanitize import sanitize_html
from apps.core.slugs import unique_slug
from apps.core.uploads import RandomUploadTo
from apps.core.validators import detect_media_type, validate_image_upload, validate_media_upload

from . import pricing
from .images import make_qr_code, make_thumbnail

UNSUPPORTED_MEDIA = "Unsupported file. Use a JPEG, PNG or WebP image, or an MP4 or WebM video."
SLUG_HELP = "Leave empty to generate it from the name."


def money_field(**kwargs):
    return models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)], **kwargs)


def size_field():
    return models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )


class DiscountType(models.TextChoices):
    PERCENTAGE = "percentage", "Percentage"
    FIXED = "fixed", "Fixed amount"


class Timestamped(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SluggedModel(models.Model):
    """`slug` is filled from `name` when left blank and then never changes on its own (stable URLs)."""

    class Meta:
        abstract = True

    def ensure_slug(self):
        if not self.slug:
            self.slug = unique_slug(type(self), self.name, instance=self)

    def save(self, *args, **kwargs):
        self.ensure_slug()
        super().save(*args, **kwargs)


# --- reference data ---------------------------------------------------------------------------------------


class Category(SluggedModel, FileCleanupModel, Timestamped):
    """A node of the category tree. The discount is only a badge on the category: product and variant
    prices stay authoritative."""

    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="children")
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=160, unique=True, blank=True, help_text=SLUG_HELP)
    image = models.ImageField(upload_to=RandomUploadTo("categories"), validators=[validate_image_upload], blank=True)
    is_flash_sale = models.BooleanField(default=False)
    is_new_arrival = models.BooleanField(default=False)
    is_best_selling = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False)
    discount_type = models.CharField(max_length=20, choices=DiscountType.choices, blank=True)
    discount_amount = money_field(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"
        constraints = [
            models.CheckConstraint(condition=Q(discount_amount__gte=0), name="category_discount_gte_0"),
            models.CheckConstraint(
                condition=~Q(discount_type=DiscountType.PERCENTAGE) | Q(discount_amount__lte=100),
                name="category_percentage_lte_100",
            ),
            models.CheckConstraint(
                condition=Q(discount_amount=0) | ~Q(discount_type=""), name="category_discount_has_type"
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def has_discount(self):
        return self.discount_amount > 0

    def clean(self):
        super().clean()
        node = self.parent
        while node is not None:  # a category can not sit below itself
            if self.pk is not None and node.pk == self.pk:
                raise ValidationError({"parent": "A category can not be its own ancestor."})
            node = node.parent


class Brand(SluggedModel, Timestamped):
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=110, unique=True, blank=True, help_text=SLUG_HELP)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(Lower("name"), name="brand_name_unique_ci")]

    def __str__(self):
        return self.name


class Tag(Timestamped):
    name = models.CharField(max_length=50)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(Lower("name"), name="tag_name_unique_ci")]

    def __str__(self):
        return self.name


class Color(Timestamped):
    name = models.CharField(max_length=50)
    hex_code = models.CharField(
        max_length=7,
        validators=[RegexValidator(r"^#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})$", "Use a hex colour such as #FF0000.")],
        help_text="For example #FF0000.",
    )

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(Lower("name"), name="color_name_unique_ci")]

    def __str__(self):
        return self.name


class Size(Timestamped):
    name = models.CharField(max_length=50)
    sort_order = models.PositiveSmallIntegerField(default=0, help_text="Smaller numbers first (S=1, M=2, L=3, ...).")

    class Meta:
        ordering = ["sort_order", "name"]
        constraints = [models.UniqueConstraint(Lower("name"), name="size_name_unique_ci")]

    def __str__(self):
        return self.name


# --- products ---------------------------------------------------------------------------------------------


class Product(SluggedModel, FileCleanupModel, Timestamped):
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=280, unique=True, blank=True, help_text=SLUG_HELP)
    sku = models.CharField("SKU", max_length=64, unique=True)
    brand = models.ForeignKey(Brand, null=True, blank=True, on_delete=models.PROTECT, related_name="products")
    categories = models.ManyToManyField(Category, blank=True, related_name="products")
    primary_category = models.ForeignKey(
        Category,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="primary_products",
        help_text="The category used for 'related products'. It is added to the categories above automatically.",
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name="products")

    short_description = models.TextField(blank=True, help_text="Rich text. HTML is cleaned when saved.")
    long_description = models.TextField(blank=True, help_text="Rich text. HTML is cleaned when saved.")

    base_price = money_field()
    discount_type = models.CharField(max_length=20, choices=DiscountType.choices, blank=True)
    discount_value = money_field(default=0)
    minimum_order_quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])

    model = models.CharField("model", max_length=100, blank=True)
    weight = models.CharField(max_length=50, blank=True, help_text='Shown as typed, e.g. "500 g".')
    dimension_width = size_field()
    dimension_height = size_field()
    dimension_depth = size_field()
    material = models.CharField(max_length=150, blank=True)
    features = models.TextField(blank=True)
    warranty_information = models.TextField(blank=True)
    shipping_information = models.TextField(blank=True)
    return_policy = models.TextField(blank=True)

    is_active = models.BooleanField(default=True, help_text="Inactive products are hidden from the shop.")
    is_flash_sale = models.BooleanField(default=False)
    is_new_arrival = models.BooleanField(default=False)
    is_best_selling = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False)

    # Denormalised counters, only ever changed by code (views, orders, reviews), never typed in by hand.
    total_views = models.PositiveIntegerField(default=0, editable=False)
    total_orders = models.PositiveIntegerField(default=0, editable=False)
    total_reviews = models.PositiveIntegerField(default=0, editable=False)
    avg_rating = models.DecimalField(max_digits=3, decimal_places=2, default=0, editable=False)

    qrcode_image = models.ImageField(upload_to=RandomUploadTo("qrcodes"), blank=True, editable=False)
    qrcode_target = models.CharField(max_length=500, blank=True, editable=False)  # the URL the QR code opens

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["is_active", "-created_at"], name="product_active_newest_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(base_price__gte=0), name="product_base_price_gte_0"),
            models.CheckConstraint(condition=Q(discount_value__gte=0), name="product_discount_gte_0"),
            models.CheckConstraint(
                condition=~Q(discount_type=DiscountType.PERCENTAGE) | Q(discount_value__lte=100),
                name="product_percentage_lte_100",
            ),
            models.CheckConstraint(
                condition=~Q(discount_type=DiscountType.FIXED) | Q(discount_value__lte=F("base_price")),
                name="product_fixed_lte_base_price",
            ),
            models.CheckConstraint(
                condition=Q(discount_value=0) | ~Q(discount_type=""), name="product_discount_has_type"
            ),
            models.CheckConstraint(condition=Q(minimum_order_quantity__gte=1), name="product_moq_gte_1"),
            models.CheckConstraint(condition=Q(avg_rating__gte=0, avg_rating__lte=5), name="product_rating_0_to_5"),
        ]

    def __str__(self):
        return self.name

    @property
    def final_price(self):
        return pricing.product_prices(self)[1]

    @property
    def has_discount(self):
        base, final = pricing.product_prices(self)
        return final < base

    def clean(self):
        super().clean()
        if self.discount_value and not self.discount_type:
            raise ValidationError({"discount_type": "Choose the discount type."})
        if self.discount_type == DiscountType.PERCENTAGE and self.discount_value > 100:
            raise ValidationError({"discount_value": "A percentage discount can not be above 100."})
        if self.discount_type == DiscountType.FIXED and self.base_price is not None:
            if self.discount_value > self.base_price:
                raise ValidationError({"discount_value": "A fixed discount can not be larger than the price."})

    def save(self, *args, **kwargs):
        self.ensure_slug()
        self.short_description = sanitize_html(self.short_description)
        self.long_description = sanitize_html(self.long_description)
        if kwargs.get("update_fields") is None:
            self._refresh_qrcode()
        super().save(*args, **kwargs)

    def _refresh_qrcode(self):
        """(Re)draw the QR code when it is missing or opens an outdated URL (new slug or FRONTEND_URL)."""
        target = f"{settings.FRONTEND_URL.rstrip('/')}/products/detail/{self.slug}"
        if self.qrcode_image and self.qrcode_target == target:
            return
        self.qrcode_image.save(f"{self.slug}.png", make_qr_code(target), save=False)
        self.qrcode_target = target


class ProductVariant(Timestamped):
    """One buyable combination (colour and/or size) of a product. Stock lives here, never on the product.
    A product with no colours or sizes has exactly one variant with neither set. Prices left empty inherit
    the product's (see `pricing.variant_prices`)."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    color = models.ForeignKey(Color, null=True, blank=True, on_delete=models.PROTECT, related_name="variants")
    size = models.ForeignKey(Size, null=True, blank=True, on_delete=models.PROTECT, related_name="variants")
    sku = models.CharField(
        "SKU", max_length=100, unique=True, blank=True, help_text="Leave empty to derive it from the product SKU."
    )
    base_price = money_field(null=True, blank=True, help_text="Empty = the product's price.")
    discount_price = money_field(
        null=True, blank=True, help_text="Final price of this variant. Empty = apply the product's discount."
    )
    stock_quantity = models.PositiveIntegerField(default=0)  # PositiveIntegerField adds CHECK (stock_quantity >= 0)
    is_default = models.BooleanField(default=False, help_text="The variant the shop picks when none is chosen.")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-is_default", "id"]
        constraints = [
            # Postgres treats NULLs as distinct: without nulls_distinct=False two "no colour, no size" rows pass.
            models.UniqueConstraint(
                fields=["product", "color", "size"], nulls_distinct=False, name="variant_unique_color_size"
            ),
            models.UniqueConstraint(
                fields=["product"], condition=Q(is_default=True), name="variant_one_default_per_product"
            ),
            models.CheckConstraint(
                condition=(
                    Q(discount_price__isnull=True) | Q(base_price__isnull=True) | Q(discount_price__lte=F("base_price"))
                ),
                name="variant_discount_price_lte_base_price",
            ),
        ]

    def __str__(self):
        return f"{self.sku or 'new variant'} ({self.label})"

    @property
    def label(self):
        """'Red / M', 'Red', 'M' or 'Default'. Snapshotted into order lines later."""
        return " / ".join(part.name for part in (self.color, self.size) if part is not None) or "Default"

    @property
    def has_options(self):
        return self.color_id is not None or self.size_id is not None

    def clean(self):
        super().clean()
        if self.product_id and self.discount_price is not None:
            message = pricing.discount_price_error(self.base_price, self.discount_price, self.product.base_price)
            if message:
                raise ValidationError({"discount_price": message})

    def save(self, *args, **kwargs):
        if not self.sku:
            self.sku = self._derive_sku()
        with transaction.atomic():
            others = ProductVariant.objects.filter(product_id=self.product_id).exclude(pk=self.pk)
            if self.is_default:
                others.filter(is_default=True).update(is_default=False)  # exactly one default per product
            elif not others.filter(is_default=True).exists():
                self.is_default = True  # the first variant of a product becomes its default
            super().save(*args, **kwargs)

    def _derive_sku(self):
        parts = [self.product.sku, *(part.name for part in (self.color, self.size) if part is not None)]
        base = "-".join(slugify(part).upper() for part in parts)[:90]
        candidate, counter = base, 1
        while ProductVariant.objects.filter(sku=candidate).exclude(pk=self.pk).exists():
            counter += 1
            candidate = f"{base}-{counter}"
        return candidate


class ProductMedia(FileCleanupModel, Timestamped):
    """A gallery image or video of a product, optionally tied to one colour. The type is read from the file's
    bytes. Images get a thumbnail drawn automatically; for a video, upload a poster image as the thumbnail."""

    class FileType(models.TextChoices):
        IMAGE = "image", "Image"
        VIDEO = "video", "Video"

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="media")
    color = models.ForeignKey(
        Color,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="media",
        help_text="Leave empty for media that belongs to the whole product.",
    )
    file = models.FileField(upload_to=RandomUploadTo("products"), validators=[validate_media_upload])
    file_type = models.CharField(max_length=10, choices=FileType.choices, editable=False)
    thumbnail = models.ImageField(
        upload_to=RandomUploadTo("products/thumbs"), validators=[validate_image_upload], blank=True
    )
    order = models.PositiveIntegerField(default=0, help_text="Smaller first. The first image is the main image.")

    class Meta:
        ordering = ["order", "id"]
        verbose_name_plural = "product media"

    def __str__(self):
        return f"{self.file_type or 'media'} #{self.pk or 'new'}"

    def save(self, *args, **kwargs):
        if self.file and not self.file._committed:  # a new or replaced upload
            kind = detect_media_type(self.file)
            if kind is None:
                raise ValidationError({"file": UNSUPPORTED_MEDIA})
            self.file_type = kind
            if kind == self.FileType.IMAGE:
                self.thumbnail.save("thumb.webp", make_thumbnail(self.file), save=False)
            elif self.thumbnail and self.thumbnail._committed:
                self.thumbnail = ""  # the old poster belonged to the previous video
        super().save(*args, **kwargs)
