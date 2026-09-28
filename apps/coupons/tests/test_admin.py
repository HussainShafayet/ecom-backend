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
