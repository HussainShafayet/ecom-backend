from io import BytesIO

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.core.validators import detect_media_type, validate_media_upload

MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 64
WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 64


def image_bytes(fmt="PNG"):
    buffer = BytesIO()
    Image.new("RGB", (8, 8), "red").save(buffer, fmt)
    return buffer.getvalue()


def upload(data, name="file.bin"):
    return SimpleUploadedFile(name, data)


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP"])
def test_images_are_detected_by_content(fmt):
    assert detect_media_type(upload(image_bytes(fmt), "wrong-name.txt")) == "image"


@pytest.mark.parametrize("data", [MP4, WEBM])
def test_videos_are_detected_by_content(data):
    assert detect_media_type(upload(data, "clip.jpg")) == "video"


@pytest.mark.parametrize("data", [b"", b"just some text", b"<html></html>", image_bytes("GIF")])
def test_everything_else_is_refused(data):
    assert detect_media_type(upload(data, "picture.png")) is None
    with pytest.raises(ValidationError):
        validate_media_upload(upload(data, "picture.png"))


def test_detection_leaves_the_file_readable_from_the_start():
    file = upload(image_bytes())
    detect_media_type(file)
    assert file.read(4) == b"\x89PNG"


def test_size_limits_are_per_type(settings):
    settings.MAX_IMAGE_UPLOAD_MB = 0
    settings.MAX_VIDEO_UPLOAD_MB = 1
    with pytest.raises(ValidationError) as image_error:
        validate_media_upload(upload(image_bytes()))
    assert image_error.value.code == "image_too_large"
    validate_media_upload(upload(MP4))  # the same tiny size is fine for a video
    settings.MAX_VIDEO_UPLOAD_MB = 0
    with pytest.raises(ValidationError) as video_error:
        validate_media_upload(upload(MP4))
    assert video_error.value.code == "video_too_large"
