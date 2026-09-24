import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.accounts.tests.helpers import authed_client, verified_user
from apps.catalog.tests.helpers import make_media, make_product
from apps.catalog.tests.test_api_products import ITEM_KEYS
from apps.wishlist.models import Favourite

pytestmark = pytest.mark.django_db

URL = "/api/v1/accounts/favourite/"


def signed_in(phone="+8801712345678"):
    user = verified_user(phone)
    return user, authed_client(user)


def saved(user):
    return list(Favourite.objects.filter(user=user).order_by("id").values_list("product_id", flat=True))


def names(client):
    response = client.get(URL)
    assert response.status_code == 200, response.content
    return [item["name"] for item in response.json()["data"]]


# --- access ---------------------------------------------------------------------------------------------
def test_favourites_need_a_login(api_client):
    assert api_client.get(URL).status_code == 401
    assert api_client.post(URL, {"product_id": 1}, format="json").status_code == 401
    assert api_client.put(URL, {"product_id": 1}, format="json").status_code == 401


def test_both_slash_variants_resolve():
    _, client = signed_in()
    for path in ("/api/v1/accounts/favourite", "/api/v1/accounts/favourite/"):
        assert client.get(path).status_code == 200, path


# --- saving ---------------------------------------------------------------------------------------------
def test_saving_a_product():
    user, client = signed_in()
    product = make_product("Mug")
    response = client.post(URL, {"product_id": product.pk}, format="json")
    assert response.status_code == 200
    assert response.json() == {"success": True, "message": "Added to your favourites.", "data": None}
    assert saved(user) == [product.pk]


def test_saving_twice_is_fine_and_changes_nothing():
    user, client = signed_in()
    product = make_product("Mug")
    for _ in range(3):
        assert client.post(URL, {"product_id": product.pk}, format="json").status_code == 200
    assert saved(user) == [product.pk]


@pytest.mark.parametrize("kind", ["unknown", "inactive"])
def test_a_product_that_is_not_there_can_not_be_saved(kind):
    user, client = signed_in()
    pk = 999999 if kind == "unknown" else make_product("Hidden", is_active=False).pk
    response = client.post(URL, {"product_id": pk}, format="json")
    assert response.status_code == 400
    assert response.json()["error"] == "This product is not available."
    assert saved(user) == []


@pytest.mark.parametrize("body", [{}, {"product_id": 0}, {"product_id": "abc"}, {"product_id": None}, [1]])
def test_bad_input_is_a_400(body):
    _, client = signed_in()
    assert client.post(URL, body, format="json").status_code == 400


def test_numeric_strings_are_accepted():
    user, client = signed_in()
    product = make_product("Mug")
    assert client.post(URL, {"product_id": str(product.pk)}, format="json").status_code == 200
    assert saved(user) == [product.pk]


def test_the_number_of_favourites_is_limited_but_resaving_one_is_not_refused(settings):
    settings.MAX_FAVOURITES_PER_USER = 2
    user, client = signed_in()
    first, second, third = (make_product(name) for name in ("A", "B", "C"))
    client.post(URL, {"product_id": first.pk}, format="json")
    client.post(URL, {"product_id": second.pk}, format="json")

    refused = client.post(URL, {"product_id": third.pk}, format="json")
    again = client.post(URL, {"product_id": first.pk}, format="json")

    assert refused.status_code == 400 and "at most 2 favourites" in refused.json()["error"]
    assert again.status_code == 200
    assert saved(user) == [first.pk, second.pk]


# --- reading --------------------------------------------------------------------------------------------
def test_the_list_is_a_plain_array_of_product_cards_all_marked_favourite():
    _, client = signed_in()
    product = make_product("Mug", base_price="250.00")
    make_media(product)
    client.post(URL, {"product_id": product.pk}, format="json")

    body = client.get(URL).json()

    assert body["success"] is True
    assert isinstance(body["data"], list)  # not paginated
    (item,) = body["data"]
    assert set(item) == ITEM_KEYS
    assert item["is_favourite"] is True
    assert item["image"].startswith("http://testserver/media/")
    assert item["base_price"] == 250.0


def test_the_list_is_empty_for_a_new_customer():
    _, client = signed_in()
    assert client.get(URL).json()["data"] == []


def test_newest_favourite_first():
    _, client = signed_in()
    for name in ("First", "Second", "Third"):
        client.post(URL, {"product_id": make_product(name).pk}, format="json")
    assert names(client) == ["Third", "Second", "First"]


def test_hidden_products_leave_the_list_but_the_favourite_is_kept():
    user, client = signed_in()
    product = make_product("Mug")
    client.post(URL, {"product_id": product.pk}, format="json")
    product.is_active = False
    product.save()
    assert names(client) == []
    assert saved(user) == [product.pk]
    product.is_active = True
    product.save()
    assert names(client) == ["Mug"]


def test_favourites_are_private():
    (mine, my_client), (theirs, their_client) = signed_in(), signed_in("+8801812345678")
    product = make_product("Mug")
    my_client.post(URL, {"product_id": product.pk}, format="json")
    assert names(their_client) == []
    their_client.put(URL, {"product_id": product.pk}, format="json")  # removing "theirs" does not touch mine
    assert saved(mine) == [product.pk]


def test_reading_costs_the_same_queries_however_many_favourites():
    user, client = signed_in()

    def count():
        with CaptureQueriesContext(connection) as context:
            assert client.get(URL).status_code == 200
        return len(context)

    for index in range(2):
        Favourite.objects.create(user=user, product=make_product(f"S{index}"))
    small = count()
    for index in range(8):
        Favourite.objects.create(user=user, product=make_product(f"L{index}"))
    assert count() == small


# --- removing -------------------------------------------------------------------------------------------
def test_removing_one_product():
    user, client = signed_in()
    keep, drop = make_product("Keep"), make_product("Drop")
    for product in (keep, drop):
        client.post(URL, {"product_id": product.pk}, format="json")
    response = client.put(URL, {"product_id": drop.pk}, format="json")
    assert response.status_code == 200
    assert response.json() == {"success": True, "message": "Removed from your favourites.", "data": None}
    assert saved(user) == [keep.pk]


def test_removing_an_array_and_ignoring_what_was_never_saved():
    user, client = signed_in()
    a, b, keep = make_product("A"), make_product("B"), make_product("Keep")
    for product in (a, b, keep):
        client.post(URL, {"product_id": product.pk}, format="json")
    response = client.put(URL, [{"product_id": a.pk}, {"product_id": b.pk}, {"product_id": 424242}], format="json")
    assert response.status_code == 200
    assert saved(user) == [keep.pk]


@pytest.mark.parametrize("body", ["text", 5, [1, 2], [{}], {"product_id": 0}, [{"product_id": "x"}]])
def test_a_bad_removal_is_a_400(body):
    _, client = signed_in()
    assert client.put(URL, body, format="json").status_code == 400


def test_too_many_items_in_one_removal_is_a_400():
    _, client = signed_in()
    assert client.put(URL, [{"product_id": 1}] * 501, format="json").status_code == 400


# --- is_favourite in the catalog ---------------------------------------------------------------------------
def test_the_catalog_marks_my_favourites_and_only_mine(api_client):
    (mine, my_client), (_, their_client) = signed_in(), signed_in("+8801812345678")
    liked, other = make_product("Liked"), make_product("Other")
    my_client.post(URL, {"product_id": liked.pk}, format="json")

    def flags(client, path):
        results = client.get(path).json()["data"]["results"]
        return {item["name"]: item["is_favourite"] for item in results}

    assert flags(my_client, "/api/v1/products/") == {"Liked": True, "Other": False}
    assert flags(their_client, "/api/v1/products/") == {"Liked": False, "Other": False}
    assert flags(api_client, "/api/v1/products/") == {"Liked": False, "Other": False}
    assert flags(my_client, "/api/v1/products/featured/") == {}
    assert my_client.get("/api/v1/products/detail/liked/").json()["data"]["is_favourite"] is True
    assert my_client.get("/api/v1/products/detail/other/").json()["data"]["is_favourite"] is False


def test_removing_a_favourite_clears_the_flag_in_the_catalog():
    _, client = signed_in()
    product = make_product("Liked")
    client.post(URL, {"product_id": product.pk}, format="json")
    client.put(URL, {"product_id": product.pk}, format="json")
    assert client.get("/api/v1/products/").json()["data"]["results"][0]["is_favourite"] is False


def test_the_catalog_list_query_count_does_not_grow_with_the_page_for_a_signed_in_customer():
    user, client = signed_in()

    def count():
        with CaptureQueriesContext(connection) as context:
            assert client.get("/api/v1/products/").status_code == 200
        return len(context)

    for index in range(2):
        Favourite.objects.create(user=user, product=make_product(f"S{index}"))
    small = count()
    for index in range(8):
        Favourite.objects.create(user=user, product=make_product(f"L{index}"))
    assert count() == small


def test_deleting_a_product_or_a_customer_removes_the_favourites():
    user, client = signed_in()
    product = make_product("Mug")
    client.post(URL, {"product_id": product.pk}, format="json")
    product.delete()
    assert Favourite.objects.count() == 0
    other = make_product("Other")
    Favourite.objects.create(user=user, product=other)
    user.delete()
    assert Favourite.objects.count() == 0
