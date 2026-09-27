"""What the storefront shows that is not a product: the shop's own identity (name, logo, contact details, social
links, the announcement bar), the pages an admin writes (About, Privacy, ...), the FAQ, and what visitors send in
(contact messages, newsletter sign-ups). Nothing here knows about products, so it stays in a template base."""
from django.core.validators import MinLengthValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from apps.core.models import FileCleanupModel
from apps.core.sanitize import sanitize_html
from apps.core.uploads import RandomUploadTo
from apps.core.validators import validate_image_upload

from .validators import http_url, validate_link, validate_map_embed

SINGLETON_ID = 1


class SiteSettings(FileCleanupModel):
    """The one row of shop-wide settings (the admin opens it straight from the menu; there is no list of them)."""

    site_name = models.CharField(max_length=60, default="My Shop", help_text="Shown in the header, the footer and the browser tab.")
    tagline = models.CharField(max_length=150, blank=True, help_text="One short line under the name in the browser tab (optional).")
    logo = models.ImageField(
        upload_to=RandomUploadTo("site"),
        validators=[validate_image_upload],
        blank=True,
        help_text="JPEG, PNG or WebP, square works best. Empty: the logo that ships with the storefront.",
    )

    announcement_enabled = models.BooleanField(default=False, help_text="Show the bar above the header.")
    announcement_text = models.CharField(max_length=200, blank=True)
    announcement_link = models.CharField(
        max_length=300,
        blank=True,
        validators=[validate_link],
        help_text="A page of this shop (/products/flash-sale) or another website (https://...). Empty: plain text.",
    )

    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=30, blank=True)
    contact_address = models.CharField(max_length=250, blank=True)
    opening_hours = models.CharField(max_length=120, blank=True, help_text="e.g. Sat - Thu: 10:00 AM - 8:00 PM")
    map_embed_url = models.CharField(
        max_length=1000,
        blank=True,
        validators=[validate_map_embed],
        help_text="The src address of an embedded map (Google Maps > Share > Embed a map). Empty: no map on the contact page.",
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "site settings"
        verbose_name_plural = "site settings"
        constraints = [models.CheckConstraint(condition=Q(id=SINGLETON_ID), name="siteconfig_one_settings_row")]

    def __str__(self):
        return self.site_name

    @classmethod
    def load(cls):
        """The row, created with the defaults if the shop has none yet (the admin uses this)."""
        return cls.objects.get_or_create(pk=SINGLETON_ID)[0]

    @classmethod
    def current(cls):
        """The row, or an unsaved one with the defaults: reading the site never writes."""
        return cls.objects.filter(pk=SINGLETON_ID).first() or cls()

    def save(self, *args, **kwargs):
        self.pk = SINGLETON_ID
        super().save(*args, **kwargs)


class SocialLink(models.Model):
    class Platform(models.TextChoices):
        FACEBOOK = "facebook", "Facebook"
        INSTAGRAM = "instagram", "Instagram"
        X = "x", "X (Twitter)"
        YOUTUBE = "youtube", "YouTube"
        LINKEDIN = "linkedin", "LinkedIn"
        TIKTOK = "tiktok", "TikTok"
        WHATSAPP = "whatsapp", "WhatsApp"
        TELEGRAM = "telegram", "Telegram"

    site = models.ForeignKey(SiteSettings, on_delete=models.CASCADE, related_name="social_links")
    platform = models.CharField(max_length=20, choices=Platform.choices)
    url = models.CharField(max_length=300, validators=[http_url], help_text="Starts with https://")
    order = models.PositiveIntegerField(default=0, help_text="Smaller first.")
    is_active = models.BooleanField(default=True, help_text="Untick to hide it without deleting it.")

    class Meta:
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["site", "platform"],
                name="siteconfig_one_link_per_platform",
                violation_error_message="This platform is already listed.",
            )
        ]

    def __str__(self):
        return self.get_platform_display()


class StaticPage(models.Model):
    """A page an admin writes: About us, Privacy policy, Terms, ... shown at /pages/<slug>."""

    class FooterGroup(models.TextChoices):
        NONE = "", "Not in the footer"
        COMPANY = "company", "Company"
        SERVICE = "service", "Customer service"
        LEGAL = "legal", "Legal (bottom row)"

    slug = models.SlugField(max_length=60, unique=True, help_text="The address of the page: /pages/<slug>. Lower case, digits and dashes.")
    title = models.CharField(max_length=150)
    body = models.TextField(
        help_text="HTML: headings (h2, h3), paragraphs, lists, links, images, tables. Scripts and styles are removed when you save."
    )
    is_published = models.BooleanField(default=True, help_text="Untick to take the page offline without deleting it.")
    footer_group = models.CharField(max_length=10, choices=FooterGroup.choices, blank=True, default=FooterGroup.NONE)
    order = models.PositiveIntegerField(default=0, help_text="Smaller first (in the footer).")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "title", "id"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        self.body = sanitize_html(self.body)
        super().save(*args, **kwargs)


class FaqItem(models.Model):
    category = models.CharField(max_length=60, blank=True, help_text="Groups the questions (Orders, Shipping, ...). Empty: General.")
    question = models.CharField(max_length=200)
    answer = models.TextField(help_text="Plain text; a new line stays a new line.")
    order = models.PositiveIntegerField(default=0, help_text="Smaller first.")
    is_active = models.BooleanField(default=True, help_text="Untick to hide it without deleting it.")

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "FAQ"
        verbose_name_plural = "FAQ"

    def __str__(self):
        return self.question


class ContactMessage(models.Model):
    """What a visitor sent with the contact form. Staff read it in the admin and mark it handled."""

    name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=30, blank=True)
    subject = models.CharField(max_length=150, blank=True)
    message = models.TextField(max_length=2000, validators=[MinLengthValidator(5)])
    created_at = models.DateTimeField(auto_now_add=True)
    is_handled = models.BooleanField(default=False, help_text="Tick once someone has answered it.")

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.name}: {self.subject or self.message[:40]}"


class NewsletterSubscriber(models.Model):
    email = models.EmailField()  # always stored lower case; unique regardless of case
    is_active = models.BooleanField(default=True, help_text="Untick to stop sending to this address.")
    subscribed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-subscribed_at", "-id"]
        constraints = [models.UniqueConstraint(Lower("email"), name="siteconfig_subscriber_email_unique")]

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        super().save(*args, **kwargs)
