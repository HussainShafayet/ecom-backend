from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import models
from django.db.models import Q

from apps.catalog.models import Category, Product, Timestamped
from apps.core.models import FileCleanupModel
from apps.core.uploads import RandomUploadTo
from apps.core.validators import detect_media_type, validate_media_upload


class Page(models.TextChoices):
    """The pages of the shop that have editable sliders and banners. The values are the URL names the frontend
    calls (`/content/pages/newarrival/`, ...)."""

    HOME = "home", "Home"
    NEW_ARRIVAL = "newarrival", "New arrivals"
    FLASH_SALE = "flashsale", "Flash sale"
    BEST_SELLING = "best_selling", "Best selling"
    FEATURED = "feature", "Featured"
    CATEGORY = "category", "Categories"


class Placement(models.TextChoices):
    IMAGE_SLIDER = "image_slider", "Image slider"
    VIDEO_SLIDER = "video_slider", "Video slider"
    LEFT_BANNER = "left_banner", "Left banner"
    RIGHT_BANNER = "right_banner", "Right banner"


class LinkType(models.TextChoices):
    PRODUCT = "product", "A product"
    CATEGORY = "category", "A category"
    EXTERNAL = "external", "Another website"


class MediaType(models.TextChoices):
    IMAGE = "image", "Image"
    VIDEO = "video", "Video"


BANNERS = (Placement.LEFT_BANNER, Placement.RIGHT_BANNER)
# What each placement can show. The frontend draws the left banner with an <img> only and the video slider with
# a <video> only; the right banner handles both.
ALLOWED_MEDIA = {
    Placement.IMAGE_SLIDER: {"image"},
    Placement.VIDEO_SLIDER: {"video"},
    Placement.LEFT_BANNER: {"image"},
    Placement.RIGHT_BANNER: {"image", "video"},
}
http_url = URLValidator(schemes=["http", "https"])  # never `javascript:` and friends: the frontend renders it as a link


class PageContent(Timestamped):
    """One row per page (created by a migration): the place in the admin where its sliders and banners live."""

    page = models.CharField(max_length=20, choices=Page.choices, unique=True)

    class Meta:
        ordering = ["id"]
        verbose_name = "page content"
        verbose_name_plural = "page content"

    def __str__(self):
        return self.get_page_display()


class ContentItem(FileCleanupModel, Timestamped):
    """A slide or a banner: a picture (or video) that links to a product, a category or another website."""

    page = models.ForeignKey(PageContent, on_delete=models.CASCADE, related_name="items")
    placement = models.CharField(
        max_length=20,
        choices=Placement.choices,
        help_text="A page has at most one active left banner and one active right banner.",
    )
    order = models.PositiveIntegerField(default=0, help_text="Smaller first.")
    link_type = models.CharField(max_length=10, choices=LinkType.choices, default=LinkType.PRODUCT)
    # Deleting a product or category takes the slides that point at it with it (nothing dead is left on the page).
    product = models.ForeignKey(Product, null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    external_link = models.CharField(max_length=500, blank=True, validators=[http_url], help_text="Starts with https://")
    media = models.FileField(
        upload_to=RandomUploadTo("content"),
        validators=[validate_media_upload],
        help_text="Slider and left banner: an image. Video slider: a video. Right banner: either.",
    )
    media_type = models.CharField(max_length=10, choices=MediaType.choices, editable=False)
    caption = models.CharField(max_length=150, blank=True)
    is_active = models.BooleanField(default=True, help_text="Untick to hide it without deleting it.")

    class Meta:
        ordering = ["page", "placement", "order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["page", "placement"],
                condition=Q(is_active=True, placement__in=BANNERS),
                name="content_one_active_banner_per_side",
                violation_error_message="This page already has an active banner on that side.",
            ),
            models.CheckConstraint(
                condition=(
                    Q(link_type=LinkType.PRODUCT, product__isnull=False, category__isnull=True, external_link="")
                    | Q(link_type=LinkType.CATEGORY, category__isnull=False, product__isnull=True, external_link="")
                    | (Q(link_type=LinkType.EXTERNAL, product__isnull=True, category__isnull=True) & ~Q(external_link=""))
                ),
                name="content_link_matches_type",
                violation_error_message="The link does not match its type.",
            ),
        ]

    def __str__(self):
        return f"{self.get_placement_display()} #{self.order} ({self.page})"

    @property
    def link(self):
        """The slug the frontend puts in its route; None for another website."""
        if self.link_type == LinkType.PRODUCT:
            return self.product.slug
        if self.link_type == LinkType.CATEGORY:
            return self.category.slug
        return None

    def _normalize(self):
        """Drop what does not apply to the chosen link type, and read the media type from the file's bytes."""
        if self.link_type != LinkType.PRODUCT:
            self.product = None
        if self.link_type != LinkType.CATEGORY:
            self.category = None
        if self.link_type != LinkType.EXTERNAL:
            self.external_link = ""
        if self.media and not self.media._committed:  # a new or replaced upload
            kind = detect_media_type(self.media)
            if kind:
                self.media_type = kind

    def _check_media_fits_placement(self):
        allowed = ALLOWED_MEDIA.get(self.placement)
        if self.media_type and allowed and self.media_type not in allowed:
            wanted = " or ".join(sorted(allowed))
            raise ValidationError({"media": f"A {self.get_placement_display().lower()} needs an {wanted}, not a {self.media_type}."})

    def clean(self):
        super().clean()
        self._normalize()
        required = {
            LinkType.PRODUCT: ("product", "Choose the product this links to."),
            LinkType.CATEGORY: ("category", "Choose the category this links to."),
            LinkType.EXTERNAL: ("external_link", "Enter the address of the website."),
        }
        field, message = required.get(self.link_type, (None, None))
        if field and not getattr(self, field):
            raise ValidationError({field: message})
        self._check_media_fits_placement()

    def save(self, *args, **kwargs):
        self._normalize()
        self._check_media_fits_placement()
        super().save(*args, **kwargs)
