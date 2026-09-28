import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db

URL = reverse("admin:dashboard_dashboardreport_changelist")


@pytest.fixture
def admin_client():
    user = get_user_model().objects.create_superuser("+8801700000000", password="s3cret-Pass!", name="Root")
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def order_manager_client():
    call_command("setup_roles")
    user = get_user_model().objects.create_user(
        "+8801700000001", password="s3cret-Pass!", name="Staff", is_staff=True, is_phone_verified=True
    )
    user.groups.add(Group.objects.get(name="Order Manager"))
    client = Client()
    client.force_login(user)
    return client


def test_a_superuser_can_open_the_dashboard(admin_client):
    response = admin_client.get(URL)

    assert response.status_code == 200
    assert b"Dashboard" in response.content


def test_an_order_manager_is_blocked(order_manager_client):
    assert order_manager_client.get(URL).status_code == 403


def test_an_anonymous_visit_is_redirected_to_login():
    response = Client().get(URL)

    assert response.status_code == 302
    assert response.url.startswith(reverse("admin:login"))


def test_the_dashboard_module_is_hidden_from_an_order_manager_on_the_admin_index(order_manager_client):
    response = order_manager_client.get(reverse("admin:index"))

    assert b"Dashboard" not in response.content


def test_the_period_query_param_selects_the_bucket(admin_client):
    response = admin_client.get(URL, {"period": "today"})

    assert response.status_code == 200
    assert response.context["period"] == "today"


def test_an_unknown_period_falls_back_to_month(admin_client):
    response = admin_client.get(URL, {"period": "nonsense"})

    assert response.status_code == 200
    assert response.context["period"] == "month"
