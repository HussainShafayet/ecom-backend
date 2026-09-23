from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import OTPRequest, User

from .helpers import PHONE, authed_client, different_code, image_upload, post, sign_in, verified_user

PROFILE = "/api/v1/accounts/profile/"
pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return verified_user(email="rahim@example.com")


@pytest.fixture
def client(user):
    return authed_client(user)


def put(client, data, **extra):
    return client.put(PROFILE, data, format=extra.pop("format", "multipart"), **extra)


def verify_new_value(client, otp_outbox, **target):
    """request-otp + verify-otp-for-profile for a new phone/email (what the Profile page does)."""
    requested = client.post("/api/v1/accounts/request-otp/", target)
    assert requested.status_code == 200, requested.content
    verified = client.post(
        "/api/v1/accounts/verify-otp-for-profile/",
        {"token": requested.json()["data"]["token"], "otp": otp_outbox[-1].code},
    )
    assert verified.status_code == 200, verified.content
    return verified


# --- reading ------------------------------------------------------------------------------------------
def test_profile_requires_a_valid_access_token(api_client):
    assert api_client.get(PROFILE).status_code == 401
    assert api_client.put(PROFILE, {"name": "X"}).status_code == 401
    api_client.credentials(HTTP_AUTHORIZATION="Bearer garbage")
    assert api_client.get(PROFILE).status_code == 401


def test_get_profile_returns_exactly_the_keys_the_frontend_reads(client):
    response = client.get(PROFILE)
    assert response.status_code == 200
    assert response.json()["data"] == {
        "name": "Rahim",
        "username": None,
        "email": "rahim@example.com",
        "phone_number": PHONE,  # a string, never null: the edit form calls .replace() on it
        "date_of_birth": None,
        "gender": "",
        "profile_picture": None,
    }


# --- plain updates ------------------------------------------------------------------------------------
def test_partial_update_multipart_changes_only_what_was_sent(client, user):
    response = put(client, {"name": "Karim", "gender": "male", "date_of_birth": "1995-04-12"})
    body = response.json()
    assert response.status_code == 200 and body["message"] == "Profile updated."
    assert body["data"]["name"] == "Karim" and body["data"]["gender"] == "male"
    assert body["data"]["date_of_birth"] == "1995-04-12"
    user.refresh_from_db()
    assert user.email == "rahim@example.com" and user.phone_number == PHONE  # untouched


def test_json_body_and_the_slashless_url_work_too(client):
    assert client.put("/api/v1/accounts/profile", {"name": "Json Name"}, format="json").status_code == 200
    assert client.get(PROFILE).json()["data"]["name"] == "Json Name"


def test_patch_is_an_alias(client):
    assert client.patch(PROFILE, {"name": "Patched"}, format="json").json()["data"]["name"] == "Patched"


def test_privileged_and_unknown_fields_are_ignored(client, user):
    put(client, {"name": "Karim", "is_staff": "true", "is_superuser": "true", "is_active": "false", "id": "999"})
    user.refresh_from_db()
    assert (user.is_staff, user.is_superuser, user.is_active) == (False, False, True) and user.pk != 999


def test_name_cannot_be_blank(client, user):
    response = client.put(PROFILE, {"name": ""}, format="json")
    assert response.status_code == 400 and "name" in response.json()["field_errors"]
    # In a multipart form an empty field means "not sent" (DRF's HTML-input rule), so nothing changes.
    assert put(client, {"name": ""}).status_code == 200
    user.refresh_from_db()
    assert user.name == "Rahim"


@pytest.mark.parametrize("bad", ["ab", "has space", "bad!char", "x" * 51])
def test_username_format(client, bad):
    response = put(client, {"username": bad})
    assert response.status_code == 400 and "username" in response.json()["field_errors"]


def test_username_is_unique_case_insensitively_but_yours_is_fine(client):
    verified_user("+8801722222222", username="Taken.Name")
    clash = put(client, {"username": "taken.name"})
    assert clash.status_code == 400 and clash.json()["errors"] == ["Username: This username is already taken."]
    assert put(client, {"username": "my_name"}).status_code == 200
    assert put(client, {"username": "my_name"}).status_code == 200  # re-saving your own is not a clash


def test_blank_username_clears_it(client, user):
    put(client, {"username": "my_name"})
    put(client, {"username": ""})
    user.refresh_from_db()
    assert user.username is None


@pytest.mark.parametrize(
    "value", [(date.today() + timedelta(days=1)).isoformat(), "1899-12-31", "not-a-date"]
)
def test_date_of_birth_must_be_a_real_past_date(client, value):
    response = put(client, {"date_of_birth": value})
    assert response.status_code == 400 and "date_of_birth" in response.json()["field_errors"]


def test_gender_choices(client):
    assert put(client, {"gender": "robot"}).status_code == 400
    assert put(client, {"gender": ""}).status_code == 200
    assert put(client, {"gender": "female"}).json()["data"]["gender"] == "female"


# --- changing the email: needs a verified new value ---------------------------------------------------
def test_new_email_is_refused_without_verification(client, user):
    response = put(client, {"email": "new@example.com"})
    assert response.status_code == 400
    assert response.json()["field_errors"]["email"] == [
        "Verify this email address with an OTP before saving it."
    ]
    user.refresh_from_db()
    assert user.email == "rahim@example.com"


def test_email_change_end_to_end(client, user, otp_outbox):
    requested = client.post("/api/v1/accounts/request-otp/", {"email": "New@Example.com"})
    assert requested.status_code == 200
    assert requested.json()["message"] == "OTP sent to n***@example.com."
    assert otp_outbox[-1].target == "new@example.com" and otp_outbox[-1].purpose == "profile_email"

    verified = client.post(
        "/api/v1/accounts/verify-otp-for-profile/",
        {"token": requested.json()["data"]["token"], "otp": otp_outbox[-1].code},
    )
    assert verified.json()["data"] == {"field": "email", "value": "new@example.com"}

    saved = put(client, {"email": "new@example.com"})
    assert saved.status_code == 200 and saved.json()["data"]["email"] == "new@example.com"
    user.refresh_from_db()
    assert user.is_email_verified is True
    assert OTPRequest.objects.get(purpose="profile_email").applied_at is not None


def test_one_verification_is_good_for_one_change_only(client, otp_outbox):
    verify_new_value(client, otp_outbox, email="a@example.com")
    assert put(client, {"email": "a@example.com"}).status_code == 200
    verify_new_value(client, otp_outbox, email="b@example.com")
    assert put(client, {"email": "b@example.com"}).status_code == 200
    # going back to a@ needs a new verification: the old one was already spent
    assert put(client, {"email": "a@example.com"}).status_code == 400


def test_a_verified_value_cannot_be_swapped_for_another(client, otp_outbox):
    verify_new_value(client, otp_outbox, email="a@example.com")
    assert put(client, {"email": "b@example.com"}).status_code == 400


def test_requested_but_never_verified_is_not_enough(client, otp_outbox):
    client.post("/api/v1/accounts/request-otp/", {"email": "a@example.com"})
    assert put(client, {"email": "a@example.com"}).status_code == 400


def test_the_verification_expires(client, otp_outbox, settings):
    verify_new_value(client, otp_outbox, email="a@example.com")
    OTPRequest.objects.update(
        consumed_at=timezone.now() - timedelta(seconds=settings.PROFILE_VERIFICATION_WINDOW_SECONDS + 5)
    )
    assert put(client, {"email": "a@example.com"}).status_code == 400


def test_saving_the_same_email_needs_no_otp_and_removing_it_needs_none_either(client, user):
    assert put(client, {"email": "RAHIM@example.com"}).status_code == 200  # same value, case-insensitive
    assert put(client, {"email": ""}).status_code == 200
    user.refresh_from_db()
    assert user.email is None and user.is_email_verified is False


def test_email_used_by_someone_else_is_refused(client, otp_outbox):
    verified_user("+8801722222222", email="Taken@Example.com")
    request = client.post("/api/v1/accounts/request-otp/", {"email": "taken@example.com"})
    assert request.status_code == 400 and otp_outbox == []
    assert put(client, {"email": "taken@example.com"}).status_code == 400


# --- changing the phone number ------------------------------------------------------------------------
def test_phone_change_end_to_end_and_login_follows_the_new_number(client, user, otp_outbox, api_client):
    new_phone = "+8801733333333"
    assert put(client, {"phone_number": new_phone}).status_code == 400  # not verified yet

    verify_new_value(client, otp_outbox, phone_number=new_phone)
    assert otp_outbox[-1].target == new_phone and otp_outbox[-1].purpose == "profile_phone"
    saved = put(client, {"phone_number": new_phone})
    assert saved.status_code == 200 and saved.json()["data"]["phone_number"] == new_phone

    user.refresh_from_db()
    assert user.phone_number == new_phone and user.is_phone_verified
    assert post(api_client, "login", {"phone_number": new_phone}).status_code == 200
    assert post(api_client, "login", {"phone_number": PHONE}).status_code == 400  # old number is gone


def test_phone_used_by_someone_else_or_already_yours(client, otp_outbox):
    verified_user("+8801722222222")
    other = client.post("/api/v1/accounts/request-otp/", {"phone_number": "+8801722222222"})
    mine = client.post("/api/v1/accounts/request-otp/", {"phone_number": PHONE})
    assert other.status_code == 400 and "already used" in other.json()["error"]
    assert mine.status_code == 400 and "already your phone number" in mine.json()["error"]
    assert put(client, {"phone_number": "+8801722222222"}).status_code == 400
    assert otp_outbox == []


# --- request-otp / verify-otp-for-profile -------------------------------------------------------------
def test_request_otp_needs_exactly_one_target(client):
    url = "/api/v1/accounts/request-otp/"
    assert client.post(url, {}).status_code == 400
    both = client.post(url, {"phone_number": "+8801711111111", "email": "a@example.com"})
    assert both.status_code == 400
    assert client.post(url, {"email": "not-an-email"}).status_code == 400
    assert client.post(url, {"phone_number": "0171"}).status_code == 400


def test_profile_otp_endpoints_require_login(api_client):
    assert api_client.post("/api/v1/accounts/request-otp/", {"email": "a@example.com"}).status_code == 401
    assert api_client.post("/api/v1/accounts/verify-otp-for-profile/", {"token": "x", "otp": "123456"}).status_code == 401


def test_wrong_profile_otp_is_a_400_never_a_401(client, otp_outbox):
    token = client.post("/api/v1/accounts/request-otp/", {"email": "a@example.com"}).json()["data"]["token"]
    response = client.post(
        "/api/v1/accounts/verify-otp-for-profile/",
        {"token": token, "otp": different_code(otp_outbox[-1].code)},
    )
    assert response.status_code == 400  # a 401 would make the frontend try to refresh and log out
    assert response.json()["errors"] == ["Invalid OTP. 4 attempts left."]


def test_someone_elses_profile_token_is_invalid(client, otp_outbox):
    token = client.post("/api/v1/accounts/request-otp/", {"email": "a@example.com"}).json()["data"]["token"]
    intruder = authed_client(verified_user("+8801755555555"))
    response = intruder.post(
        "/api/v1/accounts/verify-otp-for-profile/", {"token": token, "otp": otp_outbox[-1].code}
    )
    assert response.status_code == 400 and "Invalid or expired token" in response.json()["error"]
    assert OTPRequest.objects.get().consumed_at is None  # the rightful owner can still use it


def test_a_sign_in_otp_cannot_be_used_for_profile_verification(client, user, api_client, otp_outbox):
    login_token = post(api_client, "login", {"phone_number": PHONE}).json()["data"]["token"]
    response = client.post(
        "/api/v1/accounts/verify-otp-for-profile/", {"token": login_token, "otp": otp_outbox[-1].code}
    )
    assert response.status_code == 400
    assert sign_in(api_client, login_token, otp_outbox[-1].code).status_code == 200  # still valid for login


def test_profile_otp_must_be_six_digits(client):
    response = client.post("/api/v1/accounts/verify-otp-for-profile/", {"token": "x", "otp": "12"})
    assert response.status_code == 400 and "otp" in response.json()["field_errors"]


# --- profile picture ----------------------------------------------------------------------------------
def test_upload_profile_picture(client, user, settings):
    response = put(client, {"profile_picture": image_upload("my holiday photo.PNG")})
    url = response.json()["data"]["profile_picture"]

    assert response.status_code == 200
    assert url.startswith("http://testserver/media/profile_pictures/") and url.endswith(".png")  # absolute URL
    assert "holiday" not in url  # the original filename is never kept
    user.refresh_from_db()
    assert (settings.MEDIA_ROOT / user.profile_picture.name).exists()
    assert client.get(PROFILE).json()["data"]["profile_picture"] == url


def test_picture_only_update_leaves_the_rest_alone(client, user):
    put(client, {"profile_picture": image_upload()})
    user.refresh_from_db()
    assert user.name == "Rahim" and user.email == "rahim@example.com"


def test_replacing_the_picture_deletes_the_old_file(client, user, settings, django_capture_on_commit_callbacks):
    put(client, {"profile_picture": image_upload("a.png")})
    user.refresh_from_db()
    first = settings.MEDIA_ROOT / user.profile_picture.name
    assert first.exists()

    with django_capture_on_commit_callbacks(execute=True):
        put(client, {"profile_picture": image_upload("b.png")})
    user.refresh_from_db()
    assert not first.exists() and (settings.MEDIA_ROOT / user.profile_picture.name).exists()


@pytest.mark.parametrize("fmt,ext", [("JPEG", "jpg"), ("WEBP", "webp"), ("PNG", "png")])
def test_jpeg_png_and_webp_are_accepted(client, fmt, ext):
    assert put(client, {"profile_picture": image_upload(f"x.{ext}", fmt)}).status_code == 200


def test_gif_is_not_allowed(client):
    response = put(client, {"profile_picture": image_upload("x.gif", "GIF")})
    assert response.status_code == 400
    assert "Unsupported image type" in response.json()["errors"][0]


def test_a_file_that_is_not_an_image_is_refused_whatever_its_name(client):
    from django.core.files.uploadedfile import SimpleUploadedFile

    fake = SimpleUploadedFile("evil.png", b"<?php echo 1; ?>", content_type="image/png")
    response = put(client, {"profile_picture": fake})
    assert response.status_code == 400 and "profile_picture" in response.json()["field_errors"]


def test_too_large_picture_is_refused(client, settings):
    settings.MAX_IMAGE_UPLOAD_MB = 0
    response = put(client, {"profile_picture": image_upload()})
    assert response.status_code == 400 and "too large" in response.json()["errors"][0]
