from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.tests.helpers import verified_user
from apps.orders.models import Order
from apps.orders.tests.helpers import line, place, signed_in, stock_of, stocked

pytestmark = pytest.mark.django_db


def client_with(token):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def expired_token(user):
    token = AccessToken.for_user(user)
    token.set_exp(from_time=timezone.now() - timedelta(hours=2), lifetime=timedelta(minutes=15))
    return str(token)


# --- guests and tokens ------------------------------------------------------------------------------------------
def test_a_guest_needs_no_token(api_client):
    product, _ = stocked()
    assert place(api_client, line(product)).status_code == 201


def test_an_expired_token_is_a_401_so_the_frontend_refreshes_and_nothing_is_ordered():
    user = verified_user()
    product, variant = stocked(stock=5)

    response = place(client_with(expired_token(user)), line(product))

    assert response.status_code == 401
    assert response.json()["success"] is False and isinstance(response.json()["errors"], list)
    assert "Bearer" in response["WWW-Authenticate"]
    assert Order.objects.count() == 0 and stock_of(variant) == 5


def test_a_garbage_token_is_a_401():
    product, _ = stocked()
    response = place(client_with("not.a.token"), line(product))
    assert response.status_code == 401
    assert Order.objects.count() == 0


def test_a_token_of_a_disabled_customer_is_a_401():
    user = verified_user()
    token = str(AccessToken.for_user(user))
    user.is_active = False
    user.save()
    product, _ = stocked()
    assert place(client_with(token), line(product)).status_code == 401


def test_a_valid_token_attaches_the_customer():
    user, client = signed_in()
    product, _ = stocked()
    assert place(client, line(product)).status_code == 201
    assert Order.objects.get().user == user


# --- throttling -------------------------------------------------------------------------------------------------
def test_the_order_rate_is_configured():
    number, seconds = ScopedRateThrottle().parse_rate(ScopedRateThrottle.THROTTLE_RATES["order"])
    assert number > 0 and seconds > 0


def test_placing_orders_is_throttled_per_client(api_client, monkeypatch):
    monkeypatch.setitem(ScopedRateThrottle.THROTTLE_RATES, "order", "2/min")
    product, variant = stocked(stock=10)
    assert place(api_client, line(product)).status_code == 201
    assert place(api_client, line(product)).status_code == 201

    third = place(api_client, line(product))

    assert third.status_code == 429 and "Retry-After" in third
    assert third.json()["success"] is False
    assert stock_of(variant) == 8  # the blocked request sold nothing


def test_failed_attempts_count_too(api_client, monkeypatch):
    """Otherwise a script could probe stock levels with unlimited bad orders."""
    monkeypatch.setitem(ScopedRateThrottle.THROTTLE_RATES, "order", "2/min")
    product, _ = stocked(stock=1)
    assert place(api_client, line(product, quantity=5)).status_code == 400
    assert place(api_client, line(product, quantity=5)).status_code == 400
    assert place(api_client, line(product)).status_code == 429


def test_a_signed_in_customer_has_their_own_allowance(api_client, monkeypatch):
    monkeypatch.setitem(ScopedRateThrottle.THROTTLE_RATES, "order", "1/min")
    product, _ = stocked(stock=10)
    _, client = signed_in()
    assert place(api_client, line(product)).status_code == 201
    assert place(api_client, line(product)).status_code == 429  # the guest behind this address is used up
    assert place(client, line(product)).status_code == 201  # a customer is counted by account, not by address
