"""The Review shape the React shop expects (docs/API_CONTRACT.md section 7), and what it sends to write one."""
from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework.fields import empty
from rest_framework.utils import html

from apps.catalog.serializers import absolute_url
from apps.core.validators import validate_media_upload

from . import services
from .models import MAX_COMMENT_LENGTH, Review, ReviewMedia


class ReviewMediaSerializer(serializers.ModelSerializer):
    """`{file, type}`: the absolute URL, and the MIME type (a `<source type=...>` needs one, not just "video")."""

    file = serializers.SerializerMethodField()
    type = serializers.CharField(source="content_type", read_only=True)

    class Meta:
        model = ReviewMedia
        fields = ("file", "type")

    @extend_schema_field(OpenApiTypes.URI)
    def get_file(self, media):
        return absolute_url(self.context.get("request"), media.file)


class ReviewSerializer(serializers.ModelSerializer):
    product_id = serializers.IntegerField(read_only=True)
    user_name = serializers.SerializerMethodField()
    can_edited = serializers.SerializerMethodField(help_text="True for the signed-in author of this review.")
    media_urls = ReviewMediaSerializer(source="media", many=True, read_only=True)

    class Meta:
        model = Review
        fields = ("id", "product_id", "user_name", "rating", "comment", "created_at", "can_edited", "media_urls")

    def get_user_name(self, review) -> str:
        return services.display_name(review.user)

    def get_can_edited(self, review) -> bool:
        user = getattr(self.context.get("request"), "user", None)
        return bool(user and user.is_authenticated and review.user_id == user.pk)


class ReviewQuerySerializer(serializers.Serializer):
    product_id = serializers.IntegerField(min_value=1)


class UploadListField(serializers.ListField):
    """The uploaded files named `media`; anything else under that name is ignored. On an edit the frontend sends the
    review's existing media back as the text "[object Object]" next to any new files: only real files count."""

    child = serializers.FileField(validators=[validate_media_upload])

    def get_value(self, dictionary):
        if not html.is_html_input(dictionary):  # a JSON body can not carry files
            return empty
        files = [value for value in dictionary.getlist(self.field_name) if isinstance(value, UploadedFile)]
        return files or empty

    def to_internal_value(self, data):
        """Check every file; the errors name the file (`photo.jpg: Unsupported file...`) under one `media` key. Too
        many files are refused before any of them is looked at (`update_review` adds the files already there)."""
        if len(data) > settings.MAX_REVIEW_FILES:
            raise serializers.ValidationError(services.too_many_files_message())
        checked, problems = [], []
        for upload in data:
            try:
                checked.append(self.child.run_validation(upload))
            except serializers.ValidationError as error:
                problems.extend(f"{upload.name}: {message}" for message in error.detail)
        if problems:
            raise serializers.ValidationError(problems)
        return checked


class WriteReviewSerializer(serializers.Serializer):
    """The multipart body of POST."""

    product_id = serializers.IntegerField(min_value=1)
    rating = serializers.IntegerField(min_value=1, max_value=5)
    comment = serializers.CharField(max_length=MAX_COMMENT_LENGTH, trim_whitespace=True)
    media = UploadListField(required=False, help_text="Photos (JPEG, PNG, WebP) and videos (MP4, WebM).")


class EditReviewSerializer(WriteReviewSerializer):
    """The multipart body of PUT: every field is optional, and `product_id` may only repeat the review's own."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.required = False
