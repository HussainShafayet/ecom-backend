import pytest
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command

from .helpers import verified_user

pytestmark = pytest.mark.django_db

CATALOG_MANAGER = {
    "catalog.view_category", "catalog.add_category", "catalog.change_category", "catalog.delete_category",
    "catalog.view_brand", "catalog.add_brand", "catalog.change_brand", "catalog.delete_brand",
    "catalog.view_tag", "catalog.add_tag", "catalog.change_tag", "catalog.delete_tag",
    "catalog.view_color", "catalog.add_color", "catalog.change_color", "catalog.delete_color",
    "catalog.view_size", "catalog.add_size", "catalog.change_size", "catalog.delete_size",
    "catalog.view_product", "catalog.add_product", "catalog.change_product", "catalog.delete_product",
    "catalog.view_productvariant", "catalog.add_productvariant", "catalog.change_productvariant", "catalog.delete_productvariant",
    "catalog.view_productmedia", "catalog.add_productmedia", "catalog.change_productmedia", "catalog.delete_productmedia",
    "content.view_pagecontent", "content.change_pagecontent",
    "content.view_contentitem", "content.add_contentitem", "content.change_contentitem", "content.delete_contentitem",
    "siteconfig.view_staticpage", "siteconfig.add_staticpage", "siteconfig.change_staticpage", "siteconfig.delete_staticpage",
    "siteconfig.view_faqitem", "siteconfig.add_faqitem", "siteconfig.change_faqitem", "siteconfig.delete_faqitem",
}

ORDER_MANAGER = {
    "orders.view_order", "orders.change_order",
    "orders.view_orderitem",
    "orders.view_orderstatushistory",
    "payments.view_payment",
    "reviews.view_review", "reviews.change_review", "reviews.delete_review",
    "reviews.view_reviewmedia", "reviews.delete_reviewmedia",
    "siteconfig.view_contactmessage", "siteconfig.change_contactmessage",
    "accounts.view_user",
}

# The highest-risk over-grants: things a role must NOT be able to do.
CATALOG_MANAGER_MUST_NOT_HAVE = {
    "orders.change_order", "orders.add_order", "orders.delete_order",
    "payments.view_payment",
    "accounts.view_user", "accounts.change_user",
    "siteconfig.change_sitesettings", "siteconfig.change_contactmessage",
    "siteconfig.delete_newslettersubscriber",
}
ORDER_MANAGER_MUST_NOT_HAVE = {
    "catalog.change_product", "catalog.delete_product",
    "content.add_contentitem",
    "orders.add_order", "orders.delete_order", "orders.change_deliverycharge",
    "siteconfig.change_sitesettings", "siteconfig.delete_contactmessage",
    "accounts.change_user", "accounts.add_user", "accounts.delete_user",
    "addresses.view_address",
}


def perm_set(group):
    return {f"{p.content_type.app_label}.{p.codename}" for p in group.permissions.select_related("content_type")}


def test_creates_exactly_the_two_groups_with_the_right_permissions():
    call_command("setup_roles")
    assert set(Group.objects.values_list("name", flat=True)) == {"Catalog Manager", "Order Manager"}
    assert perm_set(Group.objects.get(name="Catalog Manager")) == CATALOG_MANAGER
    assert perm_set(Group.objects.get(name="Order Manager")) == ORDER_MANAGER


def test_neither_role_over_grants():
    call_command("setup_roles")
    catalog_manager = perm_set(Group.objects.get(name="Catalog Manager"))
    order_manager = perm_set(Group.objects.get(name="Order Manager"))
    assert not (catalog_manager & CATALOG_MANAGER_MUST_NOT_HAVE)
    assert not (order_manager & ORDER_MANAGER_MUST_NOT_HAVE)


def test_running_it_twice_is_idempotent():
    call_command("setup_roles")
    call_command("setup_roles")
    assert Group.objects.filter(name="Catalog Manager").count() == 1
    assert Group.objects.filter(name="Order Manager").count() == 1
    assert perm_set(Group.objects.get(name="Catalog Manager")) == CATALOG_MANAGER
    assert perm_set(Group.objects.get(name="Order Manager")) == ORDER_MANAGER


def test_rerunning_it_removes_a_permission_the_table_no_longer_grants():
    """Proves the command syncs (group.permissions.set), rather than only adding."""
    call_command("setup_roles")
    group = Group.objects.get(name="Catalog Manager")
    stray = Permission.objects.get(content_type__app_label="orders", codename="delete_order")
    group.permissions.add(stray)
    assert "orders.delete_order" in perm_set(group)

    call_command("setup_roles")
    assert "orders.delete_order" not in perm_set(Group.objects.get(name="Catalog Manager"))


def test_it_never_touches_a_users_groups_or_individual_permissions():
    call_command("setup_roles")
    user = verified_user(phone="+8801700000099")
    group = Group.objects.get(name="Catalog Manager")
    individual_permission = Permission.objects.get(content_type__app_label="orders", codename="view_order")
    user.groups.add(group)
    user.user_permissions.add(individual_permission)

    call_command("setup_roles")

    assert list(user.groups.all()) == [group]
    assert list(user.user_permissions.all()) == [individual_permission]
