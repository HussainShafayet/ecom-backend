"""Saving a product in the admin must not undo what the shop counted while the form was open."""
from decimal import Decimal

import pytest
from django.contrib import admin

from apps.catalog.models import Product

from .helpers import make_product

pytestmark = pytest.mark.django_db


def product_admin():
    return admin.site._registry[Product]


def counters(product):
    return tuple(getattr(product, name) for name in Product.COUNTER_FIELDS)


def test_the_counter_list_names_every_counter_the_product_has():
    columns = {field.name for field in Product._meta.concrete_fields if not field.editable}
    assert {"total_views", "total_orders", "total_reviews", "avg_rating"} <= columns
    assert set(Product.COUNTER_FIELDS) == {name for name in columns if name.startswith("total_") or name == "avg_rating"}


def test_an_edit_keeps_the_counters_the_shop_moved_meanwhile():
    product = make_product("Mug")
    loaded_by_the_form = Product.objects.get(pk=product.pk)  # the admin loads the row when the request arrives
    Product.objects.filter(pk=product.pk).update(
        total_orders=7, total_views=40, total_reviews=3, avg_rating=Decimal("4.50")
    )  # ... and an order, some page views and a review land before it saves

    loaded_by_the_form.name = "Mug XL"
    product_admin().save_model(None, loaded_by_the_form, None, change=True)

    saved = Product.objects.get(pk=product.pk)
    assert saved.name == "Mug XL"  # the edit itself was saved
    assert counters(saved) == (40, 7, 3, Decimal("4.50"))  # ... and the counters were not overwritten


def test_an_edit_still_bumps_updated_at_and_sanitises_the_description():
    product = make_product("Mug")
    before = product.updated_at
    row = Product.objects.get(pk=product.pk)
    row.short_description = "<p>Nice</p><script>alert(1)</script>"

    product_admin().save_model(None, row, None, change=True)

    saved = Product.objects.get(pk=product.pk)
    assert saved.updated_at > before
    assert "<script>" not in saved.short_description and "Nice" in saved.short_description


def test_an_edit_that_changes_the_slug_redraws_the_qr_code():
    product = make_product("Mug")
    old_target = Product.objects.get(pk=product.pk).qrcode_target
    row = Product.objects.get(pk=product.pk)
    row.slug = "mug-xl"

    product_admin().save_model(None, row, None, change=True)

    saved = Product.objects.get(pk=product.pk)
    assert saved.slug == "mug-xl"
    assert saved.qrcode_target.endswith("/products/detail/mug-xl") and saved.qrcode_target != old_target
    assert saved.qrcode_image  # a new image was stored for the new address


def test_an_edit_with_the_slug_cleared_gets_a_fresh_one_before_the_qr_code_is_drawn():
    product = make_product("Blue Mug")
    row = Product.objects.get(pk=product.pk)
    row.slug = ""

    product_admin().save_model(None, row, None, change=True)

    saved = Product.objects.get(pk=product.pk)
    assert saved.slug and saved.qrcode_target.endswith(f"/products/detail/{saved.slug}")


def test_a_new_product_is_saved_the_normal_way():
    row = Product(name="Cup", sku="CUP-1", base_price=Decimal("50.00"))
    product_admin().save_model(None, row, None, change=False)
    saved = Product.objects.get(sku="CUP-1")
    assert saved.slug == "cup" and saved.qrcode_image
