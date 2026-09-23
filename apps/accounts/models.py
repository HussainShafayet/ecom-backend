from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models

from .managers import UserManager
from .validators import phone_number_validator


class User(AbstractBaseUser, PermissionsMixin):
    """Phone-number identity. Customers have no password (OTP login); staff use one for /admin/."""

    class Gender(models.TextChoices):
        MALE = "male", "Male"
        FEMALE = "female", "Female"
        OTHER = "other", "Other"

    phone_number = models.CharField(
        max_length=14, unique=True, validators=[phone_number_validator]
    )
    email = models.EmailField(unique=True, null=True, blank=True)  # NULL (never "") when absent
    name = models.CharField(max_length=150)
    username = models.CharField(max_length=50, unique=True, null=True, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=10, choices=Gender.choices, blank=True)

    is_phone_verified = models.BooleanField(default=False)
    is_email_verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "phone_number"
    REQUIRED_FIELDS = ["name"]
    EMAIL_FIELD = "email"

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.phone_number

    def save(self, *args, **kwargs):
        # Unique columns must hold NULL, not "", when the value is missing.
        self.email = self.email.strip().lower() if self.email else None
        self.username = self.username.strip() if self.username else None
        super().save(*args, **kwargs)
