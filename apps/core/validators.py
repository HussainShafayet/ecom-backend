from collections import namedtuple

from django.conf import settings
from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError

# What a sniffed upload is: 'image' or 'video', its MIME type, and the file extension that goes with it.
MediaFormat = namedtuple("MediaFormat", ["kind", "mime", "extension"])
IMAGE_MEDIA = {
    "JPEG": MediaFormat("image", "image/jpeg", "jpg"),
    "PNG": MediaFormat("image", "image/png", "png"),
    "WEBP": MediaFormat("image", "image/webp", "webp"),
}
ALLOWED_IMAGE_FORMATS = set(IMAGE_MEDIA)
MP4 = MediaFormat("video", "video/mp4", "mp4")
WEBM = MediaFormat("video", "video/webm", "webm")
# HEIC / HEIF / AVIF photos (some phones save them) sit in the same `ftyp` container as MP4, but no browser shows
# them: they are refused, not stored as a video that can not play.
IMAGE_BRANDS = frozenset(
    {b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"hevm", b"hevs", b"mif1", b"msf1", b"avif", b"avis"}
)


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


def detect_media_format(file):
    """`MediaFormat(kind, mime, extension)` from the file's bytes (never its name or the browser's content type),
    else None.

    Images: what Pillow can decode as JPEG/PNG/WebP. Videos: MP4 (an `ftyp` box, except the HEIC/AVIF photo brands)
    or WebM (EBML header).
    """
    file.seek(0)
    head = file.read(12)
    file.seek(0)
    if len(head) >= 8 and head[4:8] == b"ftyp":
        return None if head[8:12] in IMAGE_BRANDS else MP4
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return WEBM
    try:
        with Image.open(file) as image:
            image_format = image.format
    except (UnidentifiedImageError, OSError):
        return None
    finally:
        file.seek(0)
    return IMAGE_MEDIA.get(image_format)


def detect_media_type(file):
    """'image' or 'video' from the file's bytes, else None (see `detect_media_format`)."""
    media = detect_media_format(file)
    return media.kind if media else None


def validate_media_upload(file):
    """Validator for a FileField that takes either an image or a video: type sniffing + a size limit each."""
    kind = detect_media_type(file)
    if kind is None:
        raise ValidationError(
            "Unsupported file. Use a JPEG, PNG or WebP image, or an MP4 or WebM video.", code="media_type"
        )
    max_mb = settings.MAX_IMAGE_UPLOAD_MB if kind == "image" else settings.MAX_VIDEO_UPLOAD_MB
    if file.size > max_mb * 1024 * 1024:
        raise ValidationError(f"The {kind} is too large (maximum {max_mb} MB).", code=f"{kind}_too_large")
