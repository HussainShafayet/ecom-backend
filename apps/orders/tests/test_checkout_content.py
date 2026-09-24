from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.accounts.tests.helpers import authed_client, verified_user
from apps.addresses.models import Address
from apps.orders.models import DeliveryCharge
from apps.orders.tests.helpers import CHECKOUT, set_charges, signed_in
from apps.orders.tests.test_access import client_with, expired_token

pytestmark = pytest.mark.django_db

ADDRESS = {"id", "title", "shipping_type", "address", "area", "division", "district", "thana"}


def content(client):
    response = client.get(CHECKOUT)
    assert response.status_code == 200, response.content
    return response.json()["data"]


def test_a_guest_gets_the_charges_no_addresses_and_no_user(api_client):
    body = api_client.get(CHECKOUT).json()
    assert body == {
        "success": True,
        "message": "OK",
        "data": {
            "delivery_charges": {"inside_dhaka": 60.0, "outside_dhaka": 120.0},
            "shipping_addresses": [],
            "user_info": None,
        },
    }


def test_the_charges_are_json_numbers_not_strings(api_client):
    """The frontend does `shippingCost.toFixed(2)`, which a string would break."""
    set_charges(inside="70.50", outside="130")
    charges = content(api_client)["delivery_charges"]
    assert charges == {"inside_dhaka": 70.5, "outside_dhaka": 130}
    assert all(isinstance(amount, (int, float)) for amount in charges.values())
    assert b'"inside_dhaka":70.5' in api_client.get(CHECKOUT).content.replace(b" ", b"")


def test_a_signed_in_customer_gets_their_details_and_addresses():
    user, client = signed_in("+8801712345678")
    user.email = "rahim@example.com"
    user.save()
    home = Address.objects.create(
        user=user, title="Home", shipping_type="inside_dhaka", address="House 1", area="Gulshan"
    )
    farm = Address.objects.create(
        user=user,
        shipping_type="outside_dhaka",
        address="Village",
        division="Dhaka",
        district="Gazipur",
        thana="Sreepur",
    )

    data = content(client)

    assert data["user_info"] == {"name": "Rahim", "phone_number": "+8801712345678", "email": "rahim@example.com"}
    assert isinstance(data["user_info"]["phone_number"], str)  # the frontend calls .replace() on it
    assert [a["id"] for a in data["shipping_addresses"]] == [home.pk, farm.pk]  # oldest first
    assert all(set(a) == ADDRESS for a in data["shipping_addresses"])
    assert data["shipping_addresses"][0] == {
        "id": home.pk,
        "title": "Home",
        "shipping_type": "inside_dhaka",
        "address": "House 1",
        "area": "Gulshan",
        "division": "",
        "district": "",
        "thana": "",
    }
    assert data["delivery_charges"] == {"inside_dhaka": 60.0, "outside_dhaka": 120.0}


def test_a_customer_without_an_email_gets_an_empty_string():
    _, client = signed_in()
    assert content(client)["user_info"]["email"] == ""


def test_only_the_customers_own_addresses_are_listed():
    user, client = signed_in()
    other = verified_user("+8801812345678")
    mine = Address.objects.create(user=user, shipping_type="inside_dhaka", address="Mine", area="Gulshan")
    Address.objects.create(user=other, shipping_type="inside_dhaka", address="Theirs", area="Banani")
    assert [a["id"] for a in content(client)["shipping_addresses"]] == [mine.pk]


def test_an_edited_charge_shows_at_once(api_client):
    DeliveryCharge.objects.filter(shipping_type="outside_dhaka").update(amount=Decimal("99.00"))
    assert content(api_client)["delivery_charges"]["outside_dhaka"] == 99.0


def test_a_shipping_type_without_a_charge_is_left_out(api_client):
    DeliveryCharge.objects.filter(shipping_type="outside_dhaka").delete()
    assert content(api_client)["delivery_charges"] == {"inside_dhaka": 60.0}


def test_both_slash_variants_resolve_without_redirect(api_client):
    for path in ("/api/v1/content/checkout", "/api/v1/content/checkout/"):
        assert api_client.get(path).status_code == 200, path


def test_an_expired_token_is_a_401_but_no_token_is_fine():
    user = verified_user()
    assert client_with(expired_token(user)).get(CHECKOUT).status_code == 401
    assert client_with("garbage").get(CHECKOUT).status_code == 401


def test_a_valid_token_works_through_the_real_login_helper():
    user = verified_user()
    assert authed_client(user).get(CHECKOUT).status_code == 200


def test_the_query_count_does_not_grow_with_the_addresses():
    user, client = signed_in()

    def count():
        with CaptureQueriesContext(connection) as context:
            assert client.get(CHECKOUT).status_code == 200
        return len(context)

    Address.objects.create(user=user, shipping_type="inside_dhaka", address="One", area="Gulshan")
    few = count()
    for index in range(8):
        Address.objects.create(user=user, shipping_type="inside_dhaka", address=f"More {index}", area="Gulshan")
    assert count() == few
