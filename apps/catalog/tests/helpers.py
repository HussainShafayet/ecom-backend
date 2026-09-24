from decimal import Decimal
from io import BytesIO

from django.core.files.base import ContentFile
from PIL import Image

from apps.catalog.models import Brand, Category, Color, Product, ProductVariant, Size

MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 64


def image_bytes(fmt="PNG", size=(1200, 800), color="red"):
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, fmt)
    return buffer.getvalue()


def image_file(name="photo.png", **kwargs):
    return ContentFile(image_bytes(**kwargs), name=name)


def make_category(name="Shirts", **kwargs):
    return Category.objects.create(name=name, **kwargs)


def make_product(name="Red Shirt", sku=None, base_price="1000.00", **kwargs):
    sku = sku or f"SKU-{Product.objects.count() + 1:04d}"
    return Product.objects.create(name=name, sku=sku, base_price=Decimal(base_price), **kwargs)


def make_variant(product, color=None, size=None, **kwargs):
    return ProductVariant.objects.create(product=product, color=color, size=size, **kwargs)


def make_color(name="Red", hex_code="#FF0000"):
    return Color.objects.create(name=name, hex_code=hex_code)


def make_size(name="M", sort_order=2):
    return Size.objects.create(name=name, sort_order=sort_order)


def make_brand(name="Acme"):
    return Brand.objects.create(name=name)
