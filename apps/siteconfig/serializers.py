"""The response shapes are only for the OpenAPI schema (the payloads are built in `services`); the two request
serializers validate what a visitor sends."""
from rest_framework import serializers

from .models import ContactMessage, SocialLink, StaticPage, TrustBadge


class AnnouncementSerializer(serializers.Serializer):
    text = serializers.CharField()
    link = serializers.CharField(allow_null=True, help_text="A page of the shop (/products/flash-sale), https://..., or null.")
    ends_in_seconds = serializers.IntegerField(
        allow_null=True,
        help_text="Seconds until the bar should disappear, measured by the server (rounded up, at least 1); null: no end was set.",
    )


class ContactDetailsSerializer(serializers.Serializer):
    email = serializers.CharField(allow_blank=True)
    phone = serializers.CharField(allow_blank=True)
    address = serializers.CharField(allow_blank=True)
    opening_hours = serializers.CharField(allow_blank=True)
    map_url = serializers.CharField(allow_blank=True, help_text="The src of an embedded map; empty: show no map.")


class SocialLinkSerializer(serializers.Serializer):
    platform = serializers.ChoiceField(choices=SocialLink.Platform.choices)
    url = serializers.URLField()


class TrustBadgeSerializer(serializers.Serializer):
    icon = serializers.ChoiceField(choices=TrustBadge.Icon.choices)
    title = serializers.CharField()
    subtitle = serializers.CharField(allow_blank=True)


class FooterPageSerializer(serializers.Serializer):
    slug = serializers.CharField(help_text="Open it at /pages/<slug>.")
    title = serializers.CharField()


class FooterPagesSerializer(serializers.Serializer):
    company = FooterPageSerializer(many=True)
    service = FooterPageSerializer(many=True)
    legal = FooterPageSerializer(many=True)


class SiteSerializer(serializers.Serializer):
    name = serializers.CharField()
    tagline = serializers.CharField(allow_blank=True)
    logo = serializers.URLField(allow_null=True, help_text="null: use the logo that ships with the storefront.")
    announcement = AnnouncementSerializer(allow_null=True, help_text="null: no bar.")
    contact = ContactDetailsSerializer()
    social_links = SocialLinkSerializer(many=True)
    trust_badges = TrustBadgeSerializer(many=True)
    footer_pages = FooterPagesSerializer()


class SitePayloadSerializer(serializers.Serializer):
    site = SiteSerializer()


class StaticPageSerializer(serializers.Serializer):
    slug = serializers.CharField()
    title = serializers.CharField()
    body = serializers.CharField(help_text="HTML, already cleaned of scripts and styles.")
    updated_at = serializers.DateTimeField()


class StaticPagePayloadSerializer(serializers.Serializer):
    page = StaticPageSerializer()


class FaqSerializer(serializers.Serializer):
    category = serializers.CharField(help_text="`General` when the admin left it empty.")
    question = serializers.CharField()
    answer = serializers.CharField(help_text="Plain text; a new line is a new line.")


class FaqPayloadSerializer(serializers.Serializer):
    faqs = FaqSerializer(many=True)


class ContactMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactMessage
        fields = ["name", "email", "phone", "subject", "message"]
        extra_kwargs = {
            "phone": {"required": False},
            "subject": {"required": False},
            "message": {"max_length": 2000},
        }


class NewsletterSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
