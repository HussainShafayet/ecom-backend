import pytest
from django.contrib.auth.models import Group

from apps.core.slugs import unique_slug

pytestmark = pytest.mark.django_db


# Group has no slug column; its unique `name` (max_length 150) stands in to exercise the helper on a real table.


def test_slugifies_the_value():
    assert unique_slug(Group, "Red Shirt & Co.", field="name") == "red-shirt-co"


def test_adds_a_counter_when_taken():
    Group.objects.create(name="red-shirt")
    assert unique_slug(Group, "Red Shirt", field="name") == "red-shirt-2"
    Group.objects.create(name="red-shirt-2")
    assert unique_slug(Group, "Red Shirt", field="name") == "red-shirt-3"


def test_the_row_being_saved_does_not_collide_with_itself():
    group = Group.objects.create(name="red-shirt")
    assert unique_slug(Group, "Red Shirt", instance=group, field="name") == "red-shirt"


def test_value_without_ascii_letters_falls_back_to_a_random_slug():
    slug = unique_slug(Group, "টি-শার্ট", field="name", fallback="product")
    assert slug.startswith("product-")
    assert len(slug) == len("product-") + 6


def test_the_slug_never_exceeds_the_field_length():
    slug = unique_slug(Group, "a" * 400, field="name")
    assert len(slug) <= Group._meta.get_field("name").max_length
    Group.objects.create(name=slug)
    assert len(unique_slug(Group, "a" * 400, field="name")) <= Group._meta.get_field("name").max_length
