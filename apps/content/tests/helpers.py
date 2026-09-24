from django.core.files.base import ContentFile

from apps.catalog.tests.helpers import MP4, image_file, make_product
from apps.content.models import ContentItem, LinkType, Page, PageContent, Placement


def get_page(key=Page.HOME):
    """The page row (a migration creates all six)."""
    return PageContent.objects.get(page=key)


def make_item(page=Page.HOME, placement=Placement.IMAGE_SLIDER, target=None, video=False, **kwargs):
    """A slide or banner. By default it links to a fresh product; pass `target` (a Product or a Category) or
    `link_type=` + `external_link=` to link elsewhere."""
    if "link_type" not in kwargs:
        if target is None:
            target = make_product(f"Product {ContentItem.objects.count()}")
        kwargs["link_type"] = LinkType.CATEGORY if type(target).__name__ == "Category" else LinkType.PRODUCT
        kwargs["category" if kwargs["link_type"] == LinkType.CATEGORY else "product"] = target
    media = ContentFile(MP4, name="clip.mp4") if video else image_file()
    return ContentItem.objects.create(page=get_page(page), placement=placement, media=media, **kwargs)
