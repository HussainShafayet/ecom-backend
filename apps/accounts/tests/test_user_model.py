import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

User = get_user_model()
PHONE = "+8801712345678"

pytestmark = pytest.mark.django_db


def test_user_model_is_the_custom_one():
    assert User._meta.label == "accounts.User"
    assert User.USERNAME_FIELD == "phone_number"


def test_customer_has_no_usable_password_and_is_unverified():
    user = User.objects.create_user(PHONE, name="Rahim")
    assert not user.has_usable_password()
    assert user.is_phone_verified is False
    assert user.is_staff is False and user.is_superuser is False


def test_superuser_needs_a_password_and_gets_staff_flags():
    with pytest.raises(ValueError):
        User.objects.create_superuser("+8801700000000", name="Root")
    admin = User.objects.create_superuser("+8801700000000", password="s3cret-Pass!", name="Root")
    assert admin.is_staff and admin.is_superuser and admin.is_phone_verified
    assert admin.check_password("s3cret-Pass!")


@pytest.mark.parametrize("bad", ["01712345678", "+8801712", "+88017123456789", "+1234567890123", "abc"])
def test_phone_format_is_enforced(bad):
    with pytest.raises(ValidationError):
        User.objects.create_user(bad, name="X")


def test_phone_is_required():
    with pytest.raises(ValueError):
        User.objects.create_user("", name="X")


def test_duplicate_phone_is_rejected():
    User.objects.create_user(PHONE, name="A")
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create_user(PHONE, name="B")


def test_missing_email_is_stored_as_null_so_many_users_can_omit_it():
    first = User.objects.create_user("+8801711111111", name="A", email="")
    second = User.objects.create_user("+8801722222222", name="B")
    first.refresh_from_db(), second.refresh_from_db()
    assert first.email is None and second.email is None


def test_email_is_lowercased_and_unique_case_insensitively():
    User.objects.create_user("+8801711111111", name="A", email="Rahim@Example.com")
    assert User.objects.get(phone_number="+8801711111111").email == "rahim@example.com"
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create_user("+8801722222222", name="B", email="RAHIM@example.com")


def test_blank_username_is_stored_as_null():
    user = User.objects.create_user(PHONE, name="A", username="")
    user.refresh_from_db()
    assert user.username is None
