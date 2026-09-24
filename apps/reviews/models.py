from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxLengthValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from apps.catalog.models import UNSUPPORTED_MEDIA, Product
from apps.core.models import FileCleanupModel
from apps.core.uploads import RandomUploadTo
from apps.core.validators import detect_media_format, validate_media_upload
from apps.orders.models import OrderItem

MAX_COMMENT_LENGTH = 2000


class Review(models.Model):
    """A customer's opinion of a product they received: one per customer and product. Created only by
    `services.create_review`, which checks that a delivered order contains the product. The product's
    `total_reviews` and `avg_rating` are recounted whenever a review is saved or deleted (see `receivers.py`)."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="reviews")
    # A customer who deletes their account takes their reviews with them.
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews")
    # The delivered purchase that made this review possible ("verified purchase"). Kept even if the order goes.
    order_item = models.ForeignKey(
        OrderItem, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", editable=False
    )
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.TextField(validators=[MaxLengthValidator(MAX_COMMENT_LENGTH)])
    is_approved = models.BooleanField(
        default=True,
        help_text="Reviews are shown at once. Untick to hide one from the shop (it then no longer counts in the "
        "product's rating, and its author can not edit it).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["product", "is_approved", "-created_at"], name="review_shown_idx")]
        constraints = [
            models.UniqueConstraint(fields=["user", "product"], name="review_unique_user_product"),
            models.CheckConstraint(condition=Q(rating__gte=1, rating__lte=5), name="review_rating_1_to_5"),
            models.CheckConstraint(condition=~Q(comment=""), name="review_comment_not_empty"),
        ]

    def __str__(self):
        return f"{self.rating}/5 by {self.user_id} on product {self.product_id}"


class ReviewMedia(FileCleanupModel):
    """A photo or video a customer attached to their review. The kind comes from the file's bytes, and the stored
    name gets the extension that matches it (the shop front tells images from videos by the extension)."""

    class ContentType(models.TextChoices):
        JPEG = "image/jpeg", "JPEG image"
        PNG = "image/png", "PNG image"
        WEBP = "image/webp", "WebP image"
        MP4 = "video/mp4", "MP4 video"
        WEBM = "video/webm", "WebM video"

    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="media")
    file = models.FileField(upload_to=RandomUploadTo("reviews"), validators=[validate_media_upload])
    content_type = models.CharField(max_length=20, choices=ContentType.choices, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        verbose_name_plural = "review media"

    def __str__(self):
        return f"{self.content_type or 'media'} #{self.pk or 'new'}"

    @property
    def is_video(self):
        return self.content_type.startswith("video/")

    def save(self, *args, **kwargs):
        if self.file and not self.file._committed:  # a new upload
            media = detect_media_format(self.file)
            if media is None:
                raise ValidationError({"file": UNSUPPORTED_MEDIA})
            self.content_type = media.mime
            self.file.name = f"media.{media.extension}"  # RandomUploadTo keeps the extension, never the name
        super().save(*args, **kwargs)
