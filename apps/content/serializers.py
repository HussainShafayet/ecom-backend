"""Only for the OpenAPI schema: the payload is built in `services.page_content`."""
from rest_framework import serializers

from .models import LinkType, MediaType


class ContentItemSerializer(serializers.Serializer):
    order = serializers.IntegerField(help_text="1, 2, 3... within its list (unique, so it can be a React key).")
    type = serializers.ChoiceField(choices=LinkType.choices)
    link = serializers.CharField(allow_null=True, help_text="Slug of the product or category; null for another website.")
    external_link = serializers.CharField(allow_null=True, help_text="Only for type `external`.")
    media = serializers.URLField()
    media_type = serializers.ChoiceField(choices=MediaType.choices)
    caption = serializers.CharField(allow_blank=True)


class PageContentSerializer(serializers.Serializer):
    image_sliders = ContentItemSerializer(many=True)
    video_sliders = ContentItemSerializer(many=True)
    left_banner = ContentItemSerializer(allow_null=True)
    right_banner = ContentItemSerializer(allow_null=True)


class PagePayloadSerializer(serializers.Serializer):
    page_content = PageContentSerializer()
