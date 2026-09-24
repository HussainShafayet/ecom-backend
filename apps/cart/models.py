from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.catalog.models import ProductVariant


class CartItem(models.Model):
    """One line of a signed-in customer's cart: a buyable variant and how many. Guests keep their cart in the
    browser and it is merged into this one when they sign in. Prices are never stored: the cart always shows
    the catalog's current price."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cart_items")
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name="+")
    quantity = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]  # the order things were first added
        constraints = [
            models.UniqueConstraint(fields=["user", "variant"], name="cartitem_unique_user_variant"),
            models.CheckConstraint(condition=Q(quantity__gte=1), name="cartitem_quantity_gte_1"),
        ]

    def __str__(self):
        return f"{self.quantity} x variant {self.variant_id} (user {self.user_id})"
