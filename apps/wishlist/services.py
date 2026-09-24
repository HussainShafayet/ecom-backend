from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.catalog.queries import visible_products

from .models import Favourite

MAX_MERGE_ITEMS = 500


def favourite_ids(user, product_ids):
    """The catalog's `is_favourite` hook: which of `product_ids` this user saved."""
    return set(Favourite.objects.filter(user=user, product_id__in=product_ids).values_list("product_id", flat=True))


def _lock(user):
    """One writer at a time per customer, so the limit below can not be raced past."""
    get_user_model().objects.select_for_update().get(pk=user.pk)


def add_favourite(user, product_id):
    """Save a product. Saving it twice is fine (the second call changes nothing)."""
    if not visible_products().filter(pk=product_id).exists():
        raise ValidationError("This product is not available.")
    with transaction.atomic():
        _lock(user)
        if Favourite.objects.filter(user=user, product_id=product_id).exists():
            return
        if Favourite.objects.filter(user=user).count() >= settings.MAX_FAVOURITES_PER_USER:
            raise ValidationError(
                f"You can save at most {settings.MAX_FAVOURITES_PER_USER} favourites. Remove one to add another."
            )
        Favourite.objects.create(user=user, product_id=product_id)


def remove_favourites(user, product_ids):
    """Forget these products. Ids that were never saved are ignored."""
    Favourite.objects.filter(user=user, product_id__in=product_ids).delete()


def saved_product_ids(user):
    """Ids of the visible products the user saved, newest favourite first."""
    saved = Favourite.objects.filter(user=user, product__is_active=True).order_by("-created_at", "-id")
    return list(saved.values_list("product_id", flat=True))


def _product_id(raw):
    if isinstance(raw, dict):
        raw = raw.get("product_id")
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int) and raw > 0:
        return raw
    if isinstance(raw, str) and raw.strip().isdigit() and int(raw) > 0:
        return int(raw)
    return None


def merge_guest_favourites(user, items):
    """Add what a guest saved in the browser when they sign in. `items` is untrusted: anything that is not a
    `{"product_id": <visible product>}` is skipped, saved ones are not doubled and the limit is respected."""
    if not isinstance(items, list):
        return
    wanted = list(dict.fromkeys(pid for pid in map(_product_id, items[:MAX_MERGE_ITEMS]) if pid is not None))
    if not wanted:
        return
    with transaction.atomic():
        _lock(user)
        valid = set(visible_products().filter(pk__in=wanted).values_list("pk", flat=True))
        saved = set(Favourite.objects.filter(user=user).values_list("product_id", flat=True))
        room = max(settings.MAX_FAVOURITES_PER_USER - len(saved), 0)
        fresh = [pid for pid in wanted if pid in valid and pid not in saved][:room]
        Favourite.objects.bulk_create([Favourite(user=user, product_id=pid) for pid in fresh])
