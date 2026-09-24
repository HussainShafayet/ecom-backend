"""Reviews: who may write one, and the product's rating.

`create_review` / `update_review` (one `transaction.atomic()` each):
  * a review needs a DELIVERED order of the customer that contains the product, and there is one review per customer
    and product;
  * the uploads were already checked (type from the bytes, size) by the serializer; here the number of files is
    limited, and files written to storage are removed again if the transaction fails;
  * lock order: the review row (update only), then the product row. Nothing else is locked.

The product's `total_reviews` and `avg_rating` are derived from the approved reviews and recounted by
`refresh_product_rating` (called by `receivers.py` whenever a review is saved or deleted). The product row is
locked first and stays locked until the commit, so two customers reviewing the same product at once can not
overwrite each other's numbers.
"""
import logging
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Count, Sum
from rest_framework.exceptions import NotFound, ValidationError

from apps.catalog.models import Product
from apps.orders.models import Order, OrderItem

from .models import Review, ReviewMedia

logger = logging.getLogger(__name__)

CENT = Decimal("0.01")


def display_name(user):
    """The name shown next to a review. Only the name: never the phone number or the e-mail address."""
    return user.name.strip() or "Customer"


# --- reading ----------------------------------------------------------------------------------------------------
def shown_reviews(product_id):
    """The reviews of a product the shop shows, newest first."""
    return (
        Review.objects.filter(product_id=product_id, is_approved=True)
        .select_related("user")
        .prefetch_related("media")
    )


def delivered_items(user, product_id):
    """The lines of the customer's delivered orders that are this product."""
    return OrderItem.objects.filter(order__user=user, order__status=Order.Status.DELIVERED, product_id=product_id)


# Where a customer stands with a product, so the shop can say WHY they may not review it (not just "no").
CAN_REVIEW = "can_review"  # a delivered order of theirs contains it and they have not reviewed it yet
REVIEWED = "reviewed"  # they have (a review the staff hid counts: it can not be written again)
WAITING_FOR_DELIVERY = "waiting_for_delivery"  # they ordered it and the order has not been delivered yet
NOT_PURCHASED = "not_purchased"  # signed in, but no order of theirs that is on its way or delivered contains it
GUEST = "guest"  # not signed in
STATUSES = (CAN_REVIEW, REVIEWED, WAITING_FOR_DELIVERY, NOT_PURCHASED, GUEST)
ON_ITS_WAY = (Order.Status.PENDING, Order.Status.CONFIRMED, Order.Status.PAID, Order.Status.SHIPPED)


def review_state(user, product_id):
    """`(status, order_number)`: one of `STATUSES`, and for WAITING_FOR_DELIVERY the number of the newest order the
    customer is waiting for (so the page can link to it), else None. A cancelled or refunded order counts for nothing.
    Costs at most three small queries, and one for a guest none."""
    if not user.is_authenticated:
        return GUEST, None
    if Review.objects.filter(user=user, product_id=product_id).exists():
        return REVIEWED, None
    if delivered_items(user, product_id).exists():
        return CAN_REVIEW, None
    waiting = (
        OrderItem.objects.filter(order__user=user, order__status__in=ON_ITS_WAY, product_id=product_id)
        .order_by("-order__created_at", "-id")
        .values_list("order__number", flat=True)
        .first()
    )
    return (WAITING_FOR_DELIVERY, waiting) if waiting else (NOT_PURCHASED, None)


def can_review(user, product_id):
    """True for a signed-in customer who received the product and has not reviewed it yet."""
    return review_state(user, product_id)[0] == CAN_REVIEW


# --- writing ----------------------------------------------------------------------------------------------------
def _lock_product(product_id, active_only=False):
    """Lock the product row (NO KEY UPDATE: a review row may still point at it) and say whether it exists."""
    products = Product.objects.select_for_update(no_key=True).filter(pk=product_id)
    if active_only:
        products = products.filter(is_active=True)
    return bool(list(products.values_list("pk", flat=True)))


def _discard(names):
    """Remove files written for a review whose transaction failed. Best effort: a leftover file is harmless."""
    for name in names:
        try:
            default_storage.delete(name)
        except Exception:  # noqa: BLE001 - never hide the original error behind a clean-up failure
            logger.warning("Could not remove the review file %s after a failed save.", name, exc_info=True)


def too_many_files_message():
    return f"A review can have at most {settings.MAX_REVIEW_FILES} photos or videos."


def _attach_media(review, uploads, written):
    """Store the uploads on the review (already validated), at most `MAX_REVIEW_FILES` in all."""
    if not uploads:
        return
    if review.media.count() + len(uploads) > settings.MAX_REVIEW_FILES:
        raise ValidationError({"media": [too_many_files_message()]})
    for upload in uploads:
        media = ReviewMedia(review=review, file=upload)
        media.save()
        written.append(media.file.name)


def create_review(user, product_id, rating, comment, uploads=()):
    """Write `user`'s review of `product_id`. Raises a 400 `ValidationError` when the product is not available, the
    customer already reviewed it, or no delivered order of theirs contains it. Returns the saved `Review`."""
    written = []
    try:
        with transaction.atomic():
            if not _lock_product(product_id, active_only=True):
                raise ValidationError({"product_id": ["This product is not available."]})
            if Review.objects.filter(user=user, product_id=product_id).exists():
                raise ValidationError("You have already reviewed this product. Edit your review instead.")
            item = delivered_items(user, product_id).order_by("-order__created_at", "-id").first()
            if item is None:
                raise ValidationError("You can review a product once an order that contains it has been delivered.")
            review = Review.objects.create(
                product_id=product_id, user=user, order_item=item, rating=rating, comment=comment
            )
            _attach_media(review, uploads, written)
    except Exception:
        _discard(written)
        raise
    return review


def update_review(user, review_id, changes, uploads=(), product_id=None):
    """Change the rating and/or comment (`changes`) of the customer's own review and add `uploads` to its media.
    A review that is not theirs, is hidden by the staff or does not exist is a 404. `product_id`, if the client
    sent one, must be the review's own product: a review never moves. Returns the `Review`."""
    written = []
    try:
        with transaction.atomic():
            review = (
                Review.objects.select_for_update(of=("self",), no_key=True)
                .filter(pk=review_id, user=user, is_approved=True)
                .first()
            )
            if review is None:
                raise NotFound("Review not found.")
            if product_id is not None and product_id != review.product_id:
                raise ValidationError({"product_id": ["A review can not be moved to another product."]})
            for field in ("rating", "comment"):
                if field in changes:
                    setattr(review, field, changes[field])
            if changes:
                review.save(update_fields=[*changes, "updated_at"])
            _attach_media(review, uploads, written)
    except Exception:
        _discard(written)
        raise
    return review


# --- the product's rating ---------------------------------------------------------------------------------------
def refresh_product_rating(product_id):
    """Set the product's `total_reviews` and `avg_rating` (two decimals, half up) from its approved reviews. Safe to
    call any time, any number of times."""
    with transaction.atomic():
        if not _lock_product(product_id):
            return
        stats = Review.objects.filter(product_id=product_id, is_approved=True).aggregate(
            count=Count("pk"), points=Sum("rating")
        )
        count = stats["count"]
        average = (Decimal(stats["points"]) / count).quantize(CENT, ROUND_HALF_UP) if count else Decimal("0.00")
        Product.objects.filter(pk=product_id).update(total_reviews=count, avg_rating=average)
