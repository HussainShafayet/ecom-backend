from io import BytesIO

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.core.validators import detect_media_format, detect_media_type, validate_media_upload

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


@pytest.mark.parametrize(
    "data, expected",
    [
        (image_bytes("JPEG"), ("image", "image/jpeg", "jpg")),
        (image_bytes("PNG"), ("image", "image/png", "png")),
        (image_bytes("WEBP"), ("image", "image/webp", "webp")),
        (MP4, ("video", "video/mp4", "mp4")),
        (WEBM, ("video", "video/webm", "webm")),
    ],
    ids=["jpeg", "png", "webp", "mp4", "webm"],
)
def test_the_format_says_the_kind_the_mime_type_and_the_extension(data, expected):
    assert tuple(detect_media_format(upload(data, "misleading.gif"))) == expected


@pytest.mark.parametrize("brand", [b"heic", b"heix", b"mif1", b"avif"])
def test_a_heic_or_avif_photo_is_not_taken_for_an_mp4(brand):
    photo = b"\x00\x00\x00\x18ftyp" + brand + b"\x00\x00\x00\x00mif1heic" + b"\x00" * 64
    assert detect_media_format(upload(photo, "IMG_0001.mp4")) is None
    with pytest.raises(ValidationError) as error:
        validate_media_upload(upload(photo, "IMG_0001.mp4"))
    assert error.value.code == "media_type"


@pytest.mark.parametrize("brand", [b"isom", b"mp42", b"mp41", b"avc1", b"qt  ", b"M4V "])
def test_the_usual_video_brands_are_still_mp4(brand):
    video = b"\x00\x00\x00\x18ftyp" + brand + b"\x00" * 64
    assert tuple(detect_media_format(upload(video))) == ("video", "video/mp4", "mp4")


@pytest.mark.parametrize("data", [b"", b"plain text", image_bytes("GIF")])
def test_an_unknown_format_is_none(data):
    assert detect_media_format(upload(data)) is None


def test_the_format_check_leaves_the_file_readable_from_the_start():
    file = upload(MP4)
    detect_media_format(file)
    assert file.read(8)[4:8] == b"ftyp"
