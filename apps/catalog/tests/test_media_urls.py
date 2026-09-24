"""The API hands out whatever URL the media storage gives, made absolute when it is only a path."""
from django.core.files.storage import FileSystemStorage

from apps.catalog.serializers import absolute_url


class CdnStorage(FileSystemStorage):
    """Stands in for S3 / a CDN: its URLs are absolute and live on another host."""

    def url(self, name):
        return f"https://cdn.example.com/media/{name}"


def test_a_local_media_url_becomes_absolute_on_the_host_that_was_asked(rf, settings):
    settings.ALLOWED_HOSTS = ["api.shop.example"]
    request = rf.get("/api/v1/products/", HTTP_HOST="api.shop.example")
    assert absolute_url(request, "products/a.png") == "http://api.shop.example/media/products/a.png"


def test_a_storage_url_that_is_already_absolute_is_left_alone(rf, settings):
    settings.ALLOWED_HOSTS = ["api.shop.example"]
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {"BACKEND": "apps.catalog.tests.test_media_urls.CdnStorage"},
    }
    request = rf.get("/api/v1/products/", HTTP_HOST="api.shop.example")
    assert absolute_url(request, "reviews/a.png") == "https://cdn.example.com/media/reviews/a.png"


def test_no_file_is_no_url(rf):
    assert absolute_url(rf.get("/"), "") is None
    assert absolute_url(rf.get("/"), None) is None
