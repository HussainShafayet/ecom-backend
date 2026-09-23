from django.conf import settings
from django.db import models


class Address(models.Model):
    """A saved shipping address. Location values are plain names (the frontend ships its own static
    division/district/upazila list), so there is no reference table to keep in sync."""

    class ShippingType(models.TextChoices):
        INSIDE_DHAKA = "inside_dhaka", "Inside Dhaka"
        OUTSIDE_DHAKA = "outside_dhaka", "Outside Dhaka"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="addresses")
    title = models.CharField(max_length=100, blank=True)  # "Home", "Office", ...
    shipping_type = models.CharField(max_length=20, choices=ShippingType.choices)
    address = models.CharField(max_length=500)
    area = models.CharField(max_length=100, blank=True)  # inside_dhaka only
    division = models.CharField(max_length=100, blank=True)  # outside_dhaka only
    district = models.CharField(max_length=100, blank=True)  # outside_dhaka only
    thana = models.CharField(max_length=100, blank=True)  # outside_dhaka only (upazila/thana)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "id"]  # oldest first, like the frontend appends new ones at the end
        verbose_name_plural = "addresses"

    def __str__(self):
        return f"{self.title or self.shipping_type}: {self.address[:40]}"
