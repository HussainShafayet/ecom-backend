from django.conf import settings
from django.db import models

from apps.catalog.models import Product


class Favourite(models.Model):
    """A product a signed-in customer saved for later. Guests keep theirs in the browser until they sign in."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="favourites")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["user", "product"], name="favourite_unique_user_product")]

    def __str__(self):
        return f"{self.user_id} likes {self.product_id}"
