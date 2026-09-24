"""What `/content/pages/<page>/` answers: the visible sliders and banners of one page."""
from collections import defaultdict

from django.db.models import Q

from apps.catalog.serializers import absolute_url

from .models import ContentItem, LinkType, Placement


def visible_items(page):
    """Active items of a page whose target is still there: a slide that points at a hidden product or category
    would lead to a dead page, so it is left out until the target is visible again."""
    return (
        ContentItem.objects.filter(page__page=page, is_active=True)
        .filter(
            Q(link_type=LinkType.EXTERNAL)
            | Q(link_type=LinkType.PRODUCT, product__is_active=True)
            | Q(link_type=LinkType.CATEGORY, category__is_active=True)
        )
        .select_related("product", "category")
        .order_by("order", "id")
    )


def page_content(page, request=None):
    """`{image_sliders, video_sliders, left_banner, right_banner}` of a page. Never raises for an empty page.

    `order` counts 1, 2, 3... in the order the admin arranged the items: the frontend uses it as the React key of
    a slide, so it must be unique even when the admin left every stored order at its default of 0.
    """
    by_placement = defaultdict(list)
    for item in visible_items(page):
        by_placement[item.placement].append(item)

    def entry(item, rank):
        return {
            "order": rank,
            "type": item.link_type,
            "link": item.link,
            "external_link": item.external_link or None,
            "media": absolute_url(request, item.media),
            "media_type": item.media_type,
            "caption": item.caption,
        }

    def entries(placement):
        return [entry(item, rank) for rank, item in enumerate(by_placement[placement], start=1)]

    def banner(placement):
        first = by_placement[placement][:1]  # only one is active per side; the database enforces it
        return entry(first[0], 1) if first else None

    return {
        "image_sliders": entries(Placement.IMAGE_SLIDER),
        "video_sliders": entries(Placement.VIDEO_SLIDER),
        "left_banner": banner(Placement.LEFT_BANNER),
        "right_banner": banner(Placement.RIGHT_BANNER),
    }
