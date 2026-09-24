import random
import textwrap
from decimal import Decimal
from io import BytesIO

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from PIL import Image, ImageDraw, ImageFont

from apps.catalog import services
from apps.catalog.models import Brand, Category, Color, DiscountType, Product, ProductMedia, ProductVariant, Size, Tag

CATEGORIES = {
    "Men": ["T-Shirts", "Shirts", "Jeans"],
    "Women": ["Dresses", "Tops", "Handbags"],
    "Electronics": ["Headphones", "Smart Watches", "Speakers"],
    "Home & Living": ["Kitchen", "Decor"],
    "Footwear": ["Sneakers", "Sandals"],
}
# What a leaf category sells: (kind of variants, product nouns)
KINDS = {
    "T-Shirts": ("apparel", ["Crew Neck Tee", "Graphic Tee", "Polo Shirt"]),
    "Shirts": ("apparel", ["Oxford Shirt", "Linen Shirt", "Check Shirt"]),
    "Jeans": ("apparel", ["Slim Fit Jeans", "Straight Jeans"]),
    "Dresses": ("apparel", ["Summer Dress", "Maxi Dress", "Wrap Dress"]),
    "Tops": ("apparel", ["Cotton Top", "Silk Blouse"]),
    "Handbags": ("colors", ["Tote Bag", "Shoulder Bag", "Clutch"]),
    "Headphones": ("colors", ["Wireless Headphones", "Studio Headphones", "Earbuds"]),
    "Smart Watches": ("colors", ["Fitness Watch", "Smart Watch Pro"]),
    "Speakers": ("plain", ["Bluetooth Speaker", "Soundbar"]),
    "Kitchen": ("plain", ["Chef Knife Set", "Non-stick Pan", "Coffee Grinder"]),
    "Decor": ("plain", ["Ceramic Vase", "Wall Clock", "Table Lamp"]),
    "Sneakers": ("shoes", ["Running Sneakers", "Canvas Sneakers"]),
    "Sandals": ("shoes", ["Leather Sandals", "Beach Sandals"]),
}
ADJECTIVES = ["Classic", "Urban", "Premium", "Everyday", "Lite", "Signature", "Modern", "Essential"]
BRANDS = ["Urban Nest", "Nova Tech", "StepUp", "Casa Verde", "Zenith"]
TAGS = ["cotton", "new", "summer", "wireless", "premium", "eco-friendly", "gift"]
COLORS = {
    "Red": "#D32F2F",
    "Blue": "#1976D2",
    "Black": "#212121",
    "White": "#FAFAFA",
    "Green": "#388E3C",
    "Beige": "#D7C4A3",
    "Navy": "#1A237E",
}
SIZES = {"S": 1, "M": 2, "L": 3, "XL": 4, "39": 10, "40": 11, "41": 12, "42": 13, "43": 14}
APPAREL_SIZES = ["S", "M", "L", "XL"]
SHOE_SIZES = ["39", "40", "41", "42", "43"]


class Command(BaseCommand):
    help = (
        "Fill the catalog with fake demo data: categories, brands, tags, colours, sizes and products with "
        "variants and generated images. Safe to re-run (existing SKUs are skipped). Development only."
    )

    def add_arguments(self, parser):
        parser.add_argument("--products", type=int, default=24, help="How many products to make (default 24).")
        parser.add_argument("--flush", action="store_true", help="Delete ALL catalog data first.")
        parser.add_argument("--force", action="store_true", help="Run even though DEBUG is off.")

    def handle(self, *args, products, flush, force, **options):
        if not settings.DEBUG and not force:
            raise CommandError("Refusing to add fake data while DEBUG is off. Pass --force if you really mean it.")
        with transaction.atomic():
            if flush:
                self._flush()
            leaves = self._reference_data()
            created = sum(self._product(number, leaves) for number in range(1, products + 1))
        total = Product.objects.count()
        self.stdout.write(self.style.SUCCESS(f"Catalog seeded: {created} new product(s), {total} in total."))

    def _flush(self):
        Product.objects.all().delete()  # variants and media go with it
        while Category.objects.exists():  # parents are PROTECTed: remove the leaves first
            Category.objects.filter(children__isnull=True).delete()
        for model in (Brand, Tag, Color, Size):
            model.objects.all().delete()
        self.stdout.write("Existing catalog data deleted.")

    def _reference_data(self):
        for name in BRANDS:
            Brand.objects.get_or_create(name=name)
        for name in TAGS:
            Tag.objects.get_or_create(name=name)
        for name, hex_code in COLORS.items():
            Color.objects.get_or_create(name=name, defaults={"hex_code": hex_code})
        for name, sort_order in SIZES.items():
            Size.objects.get_or_create(name=name, defaults={"sort_order": sort_order})
        leaves = []
        for index, (root_name, children) in enumerate(CATEGORIES.items()):
            root, _ = Category.objects.get_or_create(name=root_name, defaults={"is_featured": index < 3})
            for child_index, child_name in enumerate(children):
                leaf, _ = Category.objects.get_or_create(
                    name=child_name,
                    defaults={
                        "parent": root,
                        "is_new_arrival": child_index == 0,
                        "is_best_selling": child_index == 1,
                        "is_flash_sale": child_index == 2,
                    },
                )
                leaves.append(leaf)
        return leaves

    def _product(self, number, leaves):
        """Make product #number (always the same one for the same number). Returns 1 if created, 0 if it existed."""
        sku = f"SEED-{number:04d}"
        if Product.objects.filter(sku=sku).exists():
            return 0
        rng = random.Random(number)
        leaf = leaves[(number - 1) % len(leaves)]
        kind, nouns = KINDS[leaf.name]
        name = f"{rng.choice(ADJECTIVES)} {rng.choice(nouns)}"
        base_price = Decimal(rng.randrange(4, 400)) * 10 + Decimal("9.00")
        discount_type, discount_value = "", Decimal("0")
        if rng.random() < 0.4:
            if rng.random() < 0.5:
                discount_type, discount_value = DiscountType.PERCENTAGE, Decimal(rng.choice([5, 10, 15, 20, 30]))
            else:
                discount_type, discount_value = DiscountType.FIXED, Decimal(rng.choice([50, 100, 150, 200]))
                discount_value = min(discount_value, base_price)

        product = Product.objects.create(
            name=name,
            sku=sku,
            brand=Brand.objects.get(name=rng.choice(BRANDS)),
            primary_category=leaf,
            short_description=f"<p>{name}: made to last, priced to love.</p>",
            long_description=(
                f"<p><strong>{name}</strong> is part of our {leaf.name.lower()} range.</p>"
                "<ul><li>Quality materials</li><li>Easy returns</li><li>Fast delivery</li></ul>"
            ),
            base_price=base_price,
            discount_type=discount_type,
            discount_value=discount_value,
            minimum_order_quantity=rng.choice([1, 1, 1, 2]),
            model=f"M-{rng.randrange(100, 999)}",
            weight=f"{rng.randrange(100, 1500)} g",
            dimension_width=Decimal(rng.randrange(10, 60)),
            dimension_height=Decimal(rng.randrange(10, 60)),
            dimension_depth=Decimal(rng.randrange(2, 30)),
            material=rng.choice(["Cotton", "Leather", "Polyester", "Stainless steel", "Ceramic", "Plastic"]),
            features="Durable, lightweight and easy to care for.",
            warranty_information="6 months seller warranty.",
            shipping_information="Ships within 1-2 working days.",
            return_policy="7 days easy return.",
            is_featured=rng.random() < 0.25,
            is_flash_sale=rng.random() < 0.2,
            is_new_arrival=rng.random() < 0.3,
            is_best_selling=rng.random() < 0.25,
            total_views=rng.randrange(0, 5000),  # fake statistics, they do not match any real order or review
            total_orders=rng.randrange(0, 300),
            total_reviews=rng.randrange(0, 120),
            avg_rating=Decimal(rng.randrange(30, 51)) / 10,
        )
        product.categories.set([leaf, leaf.parent])
        product.tags.set(Tag.objects.filter(name__in=rng.sample(TAGS, 2)))
        services.sync_primary_category(product)

        colors = self._variants(product, kind, rng)
        self._media(product, colors, rng)
        return 1

    def _variants(self, product, kind, rng):
        """Create the variants for the product's kind. Returns the colours used (their media come next)."""
        all_colors = list(Color.objects.all())
        if kind == "plain":
            colors, sizes = [None], [None]
        elif kind == "colors":
            colors, sizes = rng.sample(all_colors, rng.randrange(1, 4)), [None]
        elif kind == "shoes":
            colors = rng.sample(all_colors, rng.randrange(1, 3))
            sizes = list(Size.objects.filter(name__in=rng.sample(SHOE_SIZES, 3)))
        else:
            colors = rng.sample(all_colors, rng.randrange(1, 4))
            sizes = list(Size.objects.filter(name__in=APPAREL_SIZES))
        for color in colors:
            for size in sizes:
                override = rng.random() < 0.15 and size is not None
                ProductVariant.objects.create(
                    product=product,
                    color=color,
                    size=size,
                    base_price=product.base_price + 100 if override else None,
                    stock_quantity=rng.choice([0, 0, 3, 8, 15, 30, 60]),
                )
        return [color for color in colors if color is not None]

    def _media(self, product, colors, rng):
        """Two product-level pictures and one per colour, drawn with Pillow (no network, no stock photos)."""
        pictures = [(None, "front", (60, 90, 140)), (None, "back", (90, 60, 140))]
        pictures += [(color, color.name, self._rgb(color.hex_code)) for color in colors]
        for order, (color, caption, rgb) in enumerate(pictures):
            ProductMedia.objects.create(
                product=product,
                color=color,
                order=order,
                file=ContentFile(self._picture(product.name, caption, rgb), name=f"{product.sku}.jpg"),
            )

    @staticmethod
    def _rgb(hex_code):
        digits = hex_code.lstrip("#")
        if len(digits) == 3:
            digits = "".join(char * 2 for char in digits)
        return tuple(int(digits[i : i + 2], 16) for i in (0, 2, 4))

    @staticmethod
    def _picture(title, caption, rgb, size=800):
        image = Image.new("RGB", (size, size), rgb)
        draw = ImageDraw.Draw(image)
        light = sum(rgb) / 3 > 140
        ink = (30, 30, 30) if light else (245, 245, 245)
        draw.multiline_text(
            (size / 2, size / 2 - 30),
            "\n".join(textwrap.wrap(title, 16)),
            font=ImageFont.load_default(size=56),
            fill=ink,
            anchor="mm",
            align="center",
        )
        draw.text((size / 2, size - 80), caption, font=ImageFont.load_default(size=36), fill=ink, anchor="mm")
        buffer = BytesIO()
        image.save(buffer, "JPEG", quality=85)
        return buffer.getvalue()
