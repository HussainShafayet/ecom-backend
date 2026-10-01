import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.coupons.tests.helpers import make_coupon

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client():
    user = get_user_model().objects.create_superuser("+8801700000000", password="s3cret-Pass!", name="Root")
    client = Client()
    client.force_login(user)
    return client


def test_the_list_page_opens(admin_client):
    make_coupon()
    response = admin_client.get(reverse("admin:coupons_coupon_changelist"))
    assert response.status_code == 200


def test_coupons_can_be_turned_off_and_on(admin_client):
    coupon = make_coupon()
    url = reverse("admin:coupons_coupon_changelist")
    admin_client.post(url, {"action": "deactivate", "_selected_action": [coupon.pk]})
    coupon.refresh_from_db()
    assert coupon.is_active is False
    admin_client.post(url, {"action": "activate", "_selected_action": [coupon.pk]})
    coupon.refresh_from_db()
    assert coupon.is_active is True


def test_times_used_is_read_only(admin_client):
    coupon = make_coupon(times_used=3)
    response = admin_client.get(reverse("admin:coupons_coupon_change", args=[coupon.pk]))
    assert response.status_code == 200
    assert b'name="times_used"' not in response.content  # shown as text, not an editable input


def change_form_data(coupon, **overrides):
    """What the change form posts back for `coupon`, with `overrides` on top."""
    data = {
        "code": coupon.code,
        "description": "",
        "discount_type": coupon.discount_type,
        "discount_value": "25.00",
        "min_order_amount": "",
        "max_discount_amount": "",
        "max_redemptions": "",
        "max_redemptions_per_customer": "",
        "valid_from_0": "",
        "valid_from_1": "",
        "valid_until_0": "",
        "valid_until_1": "",
        "is_active": "on",
        "public_title": "",
    }
    data.update(overrides)
    return data


def test_the_offer_fields_are_on_the_form(admin_client):
    coupon = make_coupon()
    response = admin_client.get(reverse("admin:coupons_coupon_change", args=[coupon.pk]))
    assert b'name="show_at_checkout"' in response.content
    assert b'name="public_title"' in response.content


def test_a_coupon_can_be_shown_at_checkout_with_a_title(admin_client):
    coupon = make_coupon()
    data = change_form_data(coupon, show_at_checkout="on", public_title="25% off your first order")
    response = admin_client.post(reverse("admin:coupons_coupon_change", args=[coupon.pk]), data)
    assert response.status_code == 302
    coupon.refresh_from_db()
    assert coupon.show_at_checkout is True and coupon.public_title == "25% off your first order"


def test_showing_a_coupon_without_a_title_is_refused(admin_client):
    coupon = make_coupon()
    response = admin_client.post(
        reverse("admin:coupons_coupon_change", args=[coupon.pk]), change_form_data(coupon, show_at_checkout="on")
    )
    assert response.status_code == 200  # the form again, with the reason
    assert b"Write the title customers will see" in response.content
    coupon.refresh_from_db()
    assert coupon.show_at_checkout is False


def test_the_list_shows_and_filters_by_what_is_suggested(admin_client):
    make_coupon(code="QUIET")
    make_coupon(code="LOUD", show_at_checkout=True, public_title="10% off")
    url = reverse("admin:coupons_coupon_changelist")
    page = admin_client.get(url)
    assert b"show_at_checkout" in page.content
    filtered = admin_client.get(url, {"show_at_checkout__exact": "1"})
    assert b"LOUD" in filtered.content and b"QUIET" not in filtered.content
