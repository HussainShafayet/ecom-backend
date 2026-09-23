from django.conf import settings
from django.core.exceptions import ValidationError

ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}


def validate_image_upload(file):
    """Use as a validator on an ImageField: size limit + real (decoded) format check.

    The format comes from the image bytes (Pillow), not from the filename or the browser's content type.
    """
    max_mb = settings.MAX_IMAGE_UPLOAD_MB
    if file.size > max_mb * 1024 * 1024:
        raise ValidationError(f"Image is too large (maximum {max_mb} MB).", code="image_too_large")
    image_format = getattr(getattr(file, "image", None), "format", None)
    if image_format not in ALLOWED_IMAGE_FORMATS:
        raise ValidationError("Unsupported image type. Use JPEG, PNG or WebP.", code="image_type")
