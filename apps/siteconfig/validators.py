import re
from urllib.parse import urlparse

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator

http_url = URLValidator(schemes=["http", "https"])  # never `javascript:` and friends: the frontend renders it as a link
_SHOP_PATH = re.compile(r"^/(?!/)[^\s\\]*$")  # "/products/flash-sale", not "//other.site" and not "/ x"

# Where a map may come from: the frontend puts the address in an <iframe>, so only the embed pages of the two
# usual map sites (host -> the path their embed pages live at) are taken.
MAP_EMBEDS = {
    "www.google.com": "/maps/embed",
    "maps.google.com": "/maps/embed",
    "www.openstreetmap.org": "/export/embed.html",
}


def validate_link(value):
    """A page of the shop ("/products/flash-sale") or a full http(s) address of another website."""
    if _SHOP_PATH.match(value):
        return
    try:
        http_url(value)
    except ValidationError:
        raise ValidationError(
            "Start with / for a page of this shop (e.g. /products/flash-sale), or with https:// for another website."
        ) from None


def validate_map_embed(value):
    """The `src` of an embedded Google Map or OpenStreetMap (Share > Embed a map), over https."""
    parsed = urlparse(value)
    wanted = MAP_EMBEDS.get(parsed.hostname or "")
    if parsed.scheme != "https" or wanted is None or not parsed.path.startswith(wanted):
        raise ValidationError(
            "Paste the src address of an embedded map: Google Maps > Share > Embed a map, "
            "or OpenStreetMap > Share > HTML embed. It starts with https://www.google.com/maps/embed "
            "or https://www.openstreetmap.org/export/embed.html."
        )
