import random
from io import BytesIO

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from PIL import Image, ImageDraw, ImageFont

from apps.catalog.models import Category, Product
from apps.content.models import ContentItem, LinkType, Page, PageContent, Placement

SLIDER_SIZE = (1200, 400)
BANNER_SIZE = (600, 600)
SLIDES_PER_PAGE = 3
CAPTIONS = ["New season", "Big savings", "Just landed", "Weekend deal", "Top picks", "Limited offer"]
PALETTE = [(52, 86, 139), (139, 52, 86), (52, 139, 96), (176, 116, 40), (96, 52, 139), (40, 120, 150)]


class Command(BaseCommand):
    help = (
        "Fill the six pages with demo sliders and banners (generated pictures) that link to seeded products and "
        "categories. Run seed_catalog first. A page that already has items is left alone. Development only."
    )

    def add_arguments(self, parser):
        parser.add_argument("--flush", action="store_true", help="Delete ALL slides and banners first.")
        parser.add_argument("--force", action="store_true", help="Run even though DEBUG is off.")

    def handle(self, *args, flush, force, **options):
        if not settings.DEBUG and not force:
            raise CommandError("Refusing to add fake data while DEBUG is off. Pass --force if you really mean it.")
        products = list(Product.objects.filter(is_active=True).order_by("id"))
        categories = list(Category.objects.filter(is_active=True).order_by("id"))
        if not products or not categories:
            raise CommandError("There are no products or categories to link to. Run seed_catalog first.")

        rng = random.Random(7)
        with transaction.atomic():
            if flush:
                for item in ContentItem.objects.all():
                    item.delete()  # one by one, so the picture files go too
                self.stdout.write("Existing slides and banners deleted.")
            created = 0
            for page in Page.values:
                content, _ = PageContent.objects.get_or_create(page=page)
                if content.items.exists():
                    continue
                created += self._fill(content, products, categories, rng)
        self.stdout.write(self.style.SUCCESS(f"Content seeded: {created} new slide(s) and banner(s)."))

    def _fill(self, content, products, categories, rng):
        slots = [(Placement.IMAGE_SLIDER, order) for order in range(SLIDES_PER_PAGE)]
        slots.append((Placement.RIGHT_BANNER, 0))
        if content.page == Page.HOME:
            slots.append((Placement.LEFT_BANNER, 0))
        for placement, order in slots:
            # The home page draws its banners as links to a product; the other links work on every slider.
            product_only = content.page == Page.HOME and placement != Placement.IMAGE_SLIDER
            self._item(content, placement, order, products, categories, rng, product_only)
        return len(slots)

    def _item(self, content, placement, order, products, categories, rng, product_only):
        caption = rng.choice(CAPTIONS)
        link_type = LinkType.PRODUCT if product_only else rng.choice([LinkType.PRODUCT, LinkType.CATEGORY])
        target = {"product": rng.choice(products)} if link_type == LinkType.PRODUCT else {"category": rng.choice(categories)}
        size = SLIDER_SIZE if placement == Placement.IMAGE_SLIDER else BANNER_SIZE
        picture = self._picture(caption, size, rng.choice(PALETTE))
        ContentItem.objects.create(
            page=content,
            placement=placement,
            order=order,
            link_type=link_type,
            caption=caption,
            media=ContentFile(picture, name=f"{content.page}-{placement}-{order}.jpg"),
            **target,
        )

    @staticmethod
    def _picture(text, size, rgb):
        image = Image.new("RGB", size, rgb)
        draw = ImageDraw.Draw(image)
        draw.text(
            (size[0] / 2, size[1] / 2),
            text,
            font=ImageFont.load_default(size=size[1] // 6),
            fill=(245, 245, 245),
            anchor="mm",
        )
        buffer = BytesIO()
        image.save(buffer, "JPEG", quality=85)
        return buffer.getvalue()
