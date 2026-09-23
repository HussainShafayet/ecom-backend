import pytest

from apps.accounts.tests.helpers import authed_client, verified_user
from apps.addresses.models import Address

LIST = "/api/v1/accounts/addresses/"
KEYS = {"id", "title", "shipping_type", "address", "area", "division", "district", "thana"}
pytestmark = pytest.mark.django_db

INSIDE = {"title": "Home", "shipping_type": "inside_dhaka", "address": "House 1, Road 2", "area": "Gulshan"}
OUTSIDE = {
    "title": "Village",
    "shipping_type": "outside_dhaka",
    "address": "Main road",
    "division": "Chattogram",
    "district": "Cox's Bazar",
    "thana": "Teknaf",
}


@pytest.fixture
def user():
    return verified_user()


@pytest.fixture
def client(user):
    return authed_client(user)


def detail(pk):
    return f"/api/v1/accounts/addresses/{pk}/"


# --- list / create ------------------------------------------------------------------------------------
def test_requires_login(api_client):
    assert api_client.get(LIST).status_code == 401
    assert api_client.post(LIST, INSIDE).status_code == 401
    assert api_client.delete(detail(1)).status_code == 401


def test_list_is_a_plain_array_not_a_paginated_object(client):
    response = client.get(LIST)
    assert response.status_code == 200 and response.json()["data"] == []


def test_create_inside_dhaka(client, user):
    response = client.post(LIST, INSIDE)
    body = response.json()
    assert response.status_code == 201 and body["success"] is True
    assert set(body["data"]) == KEYS  # exactly what the frontend reads (it needs `id` immediately)
    assert body["data"]["area"] == "Gulshan" and body["data"]["division"] == ""
    assert Address.objects.get().user == user


def test_create_outside_dhaka(client):
    data = client.post(LIST, OUTSIDE).json()["data"]
    assert (data["division"], data["district"], data["thana"], data["area"]) == (
        "Chattogram", "Cox's Bazar", "Teknaf", "",
    )


def test_the_profile_form_sends_blank_strings_for_fields_that_dont_apply(client):
    payload = {**INSIDE, "division": "", "district": "", "thana": ""}  # what Profile.js posts
    assert client.post(LIST, payload).status_code == 201


def test_inside_dhaka_needs_an_area(client):
    response = client.post(LIST, {**INSIDE, "area": ""})
    assert response.status_code == 400 and set(response.json()["field_errors"]) == {"area"}


def test_outside_dhaka_needs_division_district_and_thana(client):
    response = client.post(LIST, {"shipping_type": "outside_dhaka", "address": "x"})
    assert response.status_code == 400
    assert set(response.json()["field_errors"]) == {"division", "district", "thana"}


def test_shipping_type_and_address_are_required(client):
    assert client.post(LIST, {}).status_code == 400
    assert client.post(LIST, {**INSIDE, "shipping_type": "mars"}).status_code == 400
    assert client.post(LIST, {**INSIDE, "address": "  "}).status_code == 400


def test_stale_fields_of_the_other_shipping_type_are_cleared(client):
    payload = {**INSIDE, "division": "Dhaka", "district": "Dhaka", "thana": "Savar"}
    data = client.post(LIST, payload).json()["data"]
    assert (data["division"], data["district"], data["thana"]) == ("", "", "")


def test_title_is_optional(client):
    payload = {k: v for k, v in INSIDE.items() if k != "title"}
    assert client.post(LIST, payload).json()["data"]["title"] == ""


def test_list_shows_only_my_addresses_oldest_first(client):
    other = authed_client(verified_user("+8801722222222"))
    other.post(LIST, {**INSIDE, "title": "Not mine"})
    first = client.post(LIST, {**INSIDE, "title": "First"}).json()["data"]["id"]
    second = client.post(LIST, {**OUTSIDE, "title": "Second"}).json()["data"]["id"]
    listed = client.get(LIST).json()["data"]
    assert [a["id"] for a in listed] == [first, second]


def test_address_limit(client, settings):
    settings.MAX_ADDRESSES_PER_USER = 2
    assert client.post(LIST, INSIDE).status_code == 201
    assert client.post(LIST, INSIDE).status_code == 201
    third = client.post(LIST, INSIDE)
    assert third.status_code == 400 and "at most 2 addresses" in third.json()["error"]


def test_both_slash_forms_work(client):
    assert client.get("/api/v1/accounts/addresses").status_code == 200
    pk = client.post("/api/v1/accounts/addresses", INSIDE).json()["data"]["id"]
    assert client.get(f"/api/v1/accounts/addresses/{pk}").status_code == 200


# --- update (PUT) -------------------------------------------------------------------------------------
def test_put_with_the_whole_edited_object_like_addressitem_does(client):
    created = client.post(LIST, INSIDE).json()["data"]
    edited = {**created, "title": "Office", "address": "New street", "created_at": "x", "user": 999}
    response = client.put(detail(created["id"]), edited)
    assert response.status_code == 200
    assert response.json()["data"]["title"] == "Office" and response.json()["data"]["id"] == created["id"]
    assert Address.objects.get().user.phone_number == "+8801712345678"  # `user` in the body is ignored


def test_put_can_switch_shipping_type(client):
    created = client.post(LIST, INSIDE).json()["data"]
    switched = client.put(detail(created["id"]), {**OUTSIDE}).json()["data"]
    assert (switched["shipping_type"], switched["area"], switched["thana"]) == ("outside_dhaka", "", "Teknaf")


def test_put_switching_type_without_the_new_location_fields_is_refused(client):
    created = client.post(LIST, INSIDE).json()["data"]
    response = client.put(detail(created["id"]), {"shipping_type": "outside_dhaka"})
    assert response.status_code == 400
    assert set(response.json()["field_errors"]) == {"division", "district", "thana"}


def test_partial_put_and_patch(client):
    pk = client.post(LIST, INSIDE).json()["data"]["id"]
    assert client.put(detail(pk), {"title": "Renamed"}).json()["data"]["address"] == INSIDE["address"]
    assert client.patch(detail(pk), {"title": "Again"}).json()["data"]["title"] == "Again"


def test_get_one(client):
    pk = client.post(LIST, INSIDE).json()["data"]["id"]
    assert client.get(detail(pk)).json()["data"]["id"] == pk


# --- delete -------------------------------------------------------------------------------------------
def test_delete_answers_200_with_the_envelope(client):
    pk = client.post(LIST, INSIDE).json()["data"]["id"]
    response = client.delete(detail(pk))
    assert response.status_code == 200
    assert response.json() == {"success": True, "message": "Address deleted.", "data": None}
    assert client.delete(detail(pk)).status_code == 404


# --- ownership ----------------------------------------------------------------------------------------
def test_other_users_addresses_are_invisible_and_untouchable(client):
    owner = authed_client(verified_user("+8801722222222"))
    pk = owner.post(LIST, INSIDE).json()["data"]["id"]

    assert client.get(detail(pk)).status_code == 404
    assert client.put(detail(pk), {"title": "Hacked"}).status_code == 404
    assert client.delete(detail(pk)).status_code == 404  # 404, not 403: it doesn't exist for you
    assert Address.objects.get(pk=pk).title == "Home"
