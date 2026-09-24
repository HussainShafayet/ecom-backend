"""Image generation for the catalog: gallery thumbnails and the QR code of a product page."""
from io import BytesIO

import qrcode
from django.core.files.base import ContentFile
from PIL import Image, ImageOps

THUMBNAIL_SIZE = (480, 480)


def make_thumbnail(file):
    """A WebP thumbnail (fits in 480x480, keeps transparency) of an uploaded image, as a ContentFile."""
    file.seek(0)
    with Image.open(file) as source:
        image = ImageOps.exif_transpose(source)  # phone photos carry their rotation in EXIF
        image.thumbnail(THUMBNAIL_SIZE)
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA" if image.has_transparency_data else "RGB")
        buffer = BytesIO()
        image.save(buffer, "WEBP", quality=82)
    file.seek(0)
    return ContentFile(buffer.getvalue())


def make_qr_code(url):
    """A PNG QR code that opens `url`, as a ContentFile."""
    buffer = BytesIO()
    qrcode.make(url, box_size=8, border=2).save(buffer, "PNG")
    return ContentFile(buffer.getvalue())
