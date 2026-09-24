import pytest

from apps.accounts.tests.helpers import verified_user
from apps.catalog.tests.helpers import make_product
from apps.wishlist import services
from apps.wishlist.models import Favourite

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return verified_user()


def saved(user):
    return list(Favourite.objects.filter(user=user).order_by("id").values_list("product_id", flat=True))


def test_a_guests_favourites_are_saved(user):
    a, b = make_product("A"), make_product("B")
    services.merge_guest_favourites(user, [{"product_id": a.pk}, {"product_id": b.pk}])
    assert saved(user) == [a.pk, b.pk]


def test_saved_ones_and_repeats_are_not_doubled(user):
    a, b = make_product("A"), make_product("B")
    Favourite.objects.create(user=user, product=a)
    services.merge_guest_favourites(user, [{"product_id": a.pk}, {"product_id": b.pk}, {"product_id": b.pk}])
    assert saved(user) == [a.pk, b.pk]


def test_ids_may_be_numeric_strings(user):
    a = make_product("A")
    services.merge_guest_favourites(user, [{"product_id": str(a.pk)}])
    assert saved(user) == [a.pk]


def test_hidden_and_unknown_products_are_skipped(user):
    shown, hidden = make_product("Shown"), make_product("Hidden", is_active=False)
    services.merge_guest_favourites(user, [{"product_id": hidden.pk}, {"product_id": 424242}, {"product_id": shown.pk}])
    assert saved(user) == [shown.pk]


@pytest.mark.parametrize(
    "garbage",
    [None, "text", 7, [], {}, {"product_id": None}, {"product_id": 0}, {"product_id": -2}, {"product_id": 1.5},
     {"product_id": True}, {"product_id": "abc"}, {"quantity": 2}],
)  # fmt: skip
def test_garbage_never_raises_and_saves_nothing(user, garbage):
    make_product("P")
    services.merge_guest_favourites(user, [garbage])
    assert saved(user) == []


def test_something_that_is_not_a_list_is_ignored(user):
    make_product("P")
    for junk in (None, "x", {"product_id": 1}, 5):
        services.merge_guest_favourites(user, junk)
    assert saved(user) == []


def test_the_limit_is_respected_keeping_what_the_account_already_has(user, settings):
    settings.MAX_FAVOURITES_PER_USER = 3
    old = make_product("Old")
    Favourite.objects.create(user=user, product=old)
    fresh = [make_product(f"P{index}") for index in range(4)]
    services.merge_guest_favourites(user, [{"product_id": p.pk} for p in fresh])
    assert saved(user) == [old.pk, fresh[0].pk, fresh[1].pk]


def test_only_the_first_items_are_read(user, settings):
    settings.MAX_FAVOURITES_PER_USER = 10_000
    products = [make_product(f"P{index}") for index in range(services.MAX_MERGE_ITEMS + 5)]
    services.merge_guest_favourites(user, [{"product_id": p.pk} for p in products])
    assert len(saved(user)) == services.MAX_MERGE_ITEMS
