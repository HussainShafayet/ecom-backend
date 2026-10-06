"""The stock history: every move of a variant's stock leaves one line (`StockMovement`), written by the code that moves it, in the same
transaction. Sales, cancellations, goods a customer sent back (damaged units included) and hand-edits are covered here."""
from types import SimpleNamespace

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import Client, RequestFactory
from django.urls import reverse

from apps.catalog.models import ProductVariant, StockMovement
from apps.orders import services as order_services
from apps.orders.models import Order
from apps.orders.tests.helpers import line, make_order, signed_in, stocked
from apps.returns import services as return_services
from apps.returns.models import ReturnRequest
from apps.returns.tests.helpers import body, delivered_order, returns_url

from .helpers import make_product, make_variant

pytestmark = pytest.mark.django_db

Kind = StockMovement.Kind


def history(variant):
    return list(StockMovement.objects.filter(variant=variant).order_by("id"))


def staff():
    return get_user_model().objects.create_superuser("+8801700000000", password="s3cret-Pass!", name="Root")


# --- a new variant -----------------------------------------------------------------------------------------------
def test_a_new_variant_with_stock_starts_its_history():
    _, variant = stocked("Mug", stock=10)
    (entry,) = history(variant)
    assert (entry.kind, entry.change, entry.stock_after, entry.damaged_change) == (Kind.MANUAL, 10, 10, 0)
    assert entry.sku == variant.sku
    assert entry.name == "Mug (Default)"


def test_a_new_variant_without_stock_has_no_history_yet():
    _, variant = stocked("Mug", stock=0)
    assert history(variant) == []


# --- a sale ------------------------------------------------------------------------------------------------------
def test_an_order_writes_one_line_per_variant_with_the_order_number():
    mug, mug_v = stocked("Mug", stock=10)
    shirt, shirt_v = stocked("Shirt", stock=4)
    order = make_order(line(mug, mug_v, 3), line(shirt, shirt_v, 1))
    (mug_line,) = [entry for entry in history(mug_v) if entry.kind == Kind.SALE]
    (shirt_line,) = [entry for entry in history(shirt_v) if entry.kind == Kind.SALE]
    assert (mug_line.change, mug_line.stock_after, mug_line.reference, mug_line.by) == (-3, 7, order.number, None)
    assert (shirt_line.change, shirt_line.stock_after) == (-1, 3)


def test_the_same_variant_listed_twice_is_one_line():
    mug, mug_v = stocked("Mug", stock=10)
    make_order(line(mug, mug_v, 2), line(mug, mug_v, 3))
    (sale,) = [entry for entry in history(mug_v) if entry.kind == Kind.SALE]
    assert (sale.change, sale.stock_after) == (-5, 5)


def test_a_signed_in_customers_sale_names_them():
    user, _ = signed_in()
    mug, mug_v = stocked("Mug", stock=10)
    make_order(line(mug, mug_v, 1), user=user)
    (sale,) = [entry for entry in history(mug_v) if entry.kind == Kind.SALE]
    assert sale.by == user


def test_an_order_that_is_refused_leaves_no_line():
    mug, mug_v = stocked("Mug", stock=2)
    with pytest.raises(Exception):
        make_order(line(mug, mug_v, 5))
    assert [entry.kind for entry in history(mug_v)] == [Kind.MANUAL]  # only the variant's own start


# --- an order put back -------------------------------------------------------------------------------------------
def test_cancelling_an_order_writes_a_line_that_gives_the_units_back():
    mug, mug_v = stocked("Mug", stock=10)
    order = make_order(line(mug, mug_v, 3))
    admin_user = staff()
    order_services.change_status(order, Order.Status.CANCELLED, by=admin_user, note="Customer called.")
    put_back = history(mug_v)[-1]
    assert (put_back.kind, put_back.change, put_back.stock_after) == (Kind.RESTOCK, 3, 10)
    assert (put_back.reference, put_back.by) == (order.number, admin_user)


def test_a_status_move_that_does_not_restock_writes_nothing():
    mug, mug_v = stocked("Mug", stock=10)
    order = make_order(line(mug, mug_v, 3))
    before = StockMovement.objects.count()
    order_services.change_status(order, Order.Status.CONFIRMED)
    assert StockMovement.objects.count() == before


# --- goods a customer sent back -----------------------------------------------------------------------------------
def received_return(good, damaged, units=3):
    """A delivered order of `units` mugs, a request for all of them, approved; the goods come back as `good` fine and `damaged` damaged."""
    user, client = signed_in()
    mug, mug_v = stocked("Mug", stock=10, base_price="500.00")
    order = delivered_order(user, line(mug, mug_v, units))
    client.post(returns_url(order), body(order, (0, units)), format="json")
    request = ReturnRequest.objects.get(order=order)
    return_services.change_status(request, ReturnRequest.Status.APPROVED)
    item = request.items.get()
    staff_user = staff()
    return_services.receive_goods(request, [{"item_id": item.pk, "good": good, "damaged": damaged}], by=staff_user)
    return mug_v, order, request, staff_user


def test_goods_that_came_back_fine_go_into_the_history_as_stock_added():
    variant, order, request, staff_user = received_return(good=3, damaged=0)
    entry = history(variant)[-1]
    assert (entry.kind, entry.change, entry.damaged_change, entry.stock_after) == (Kind.RETURN, 3, 0, 10)
    assert entry.reference == f"Return #{request.pk} of {order.number}"
    assert entry.by == staff_user


def test_damaged_units_are_in_the_history_without_moving_the_stock():
    variant, _, _, _ = received_return(good=1, damaged=2)
    entry = history(variant)[-1]
    assert (entry.change, entry.damaged_change, entry.stock_after) == (1, 2, 8)  # 10 - 3 sold, + 1 fine; the 2 damaged are not stock


def test_a_return_of_only_damaged_units_still_leaves_a_line_with_no_stock_change():
    variant, _, _, _ = received_return(good=0, damaged=3)
    entry = history(variant)[-1]
    assert (entry.kind, entry.change, entry.damaged_change, entry.stock_after) == (Kind.RETURN, 0, 3, 7)


# --- a hand-edit ---------------------------------------------------------------------------------------------------
def test_a_hand_edit_is_measured_against_the_row_as_it_is_now_not_as_the_form_showed_it():
    mug, mug_v = stocked("Mug", stock=10)
    on_the_form = ProductVariant.objects.get(pk=mug_v.pk)  # the admin loaded the row ...
    make_order(line(mug, mug_v, 2))  # ... an order took two meanwhile ...
    on_the_form.stock_quantity = 12  # ... and the person typed 12
    on_the_form.save()
    entry = history(mug_v)[-1]
    assert (entry.kind, entry.change, entry.stock_after) == (Kind.MANUAL, 4, 12)  # from the 8 that were really there


def test_saving_a_variant_without_touching_the_stock_writes_no_line():
    _, variant = stocked("Mug", stock=10)
    count = StockMovement.objects.count()
    variant.is_active = False
    variant.save()  # same stock as the row has
    variant.stock_quantity = 99
    variant.save(update_fields=["is_active"])  # the stock is not among the fields written
    assert StockMovement.objects.count() == count
    variant.refresh_from_db()
    assert variant.stock_quantity == 10


def test_the_admin_names_who_typed_the_new_stock():
    _, variant = stocked("Mug", stock=10)
    person = staff()
    variant.stock_quantity = 25
    formset = SimpleNamespace(model=ProductVariant, forms=[SimpleNamespace(instance=variant)], save=variant.save)
    request = RequestFactory().post("/")
    request.user = person
    product_admin = admin.site._registry[type(variant.product)]
    product_admin.save_formset(request, None, formset, True)
    entry = history(variant)[-1]
    assert (entry.change, entry.stock_after, entry.by) == (15, 25, person)


# --- what the history keeps ----------------------------------------------------------------------------------------
def test_a_deleted_variant_keeps_its_history_under_its_sku_and_name():
    mug = make_product("Mug")
    variant = make_variant(mug, stock_quantity=5, sku="MUG-RED")
    variant.delete()
    entry = StockMovement.objects.get(sku="MUG-RED")
    assert (entry.variant_id, entry.name, entry.change) == (None, "Mug (Default)", 5)


def test_a_line_that_moves_nothing_cannot_be_stored():
    _, variant = stocked("Mug", stock=1)
    with pytest.raises(IntegrityError), transaction.atomic():
        StockMovement.objects.create(
            variant=variant, sku=variant.sku, name="Mug", kind=Kind.MANUAL, change=0, damaged_change=0, stock_after=1
        )


# --- the admin page -------------------------------------------------------------------------------------------------
def test_the_history_page_lists_the_lines_and_finds_them_by_order_number():
    mug, mug_v = stocked("Mug", stock=10)
    order = make_order(line(mug, mug_v, 3))
    client = Client()
    client.force_login(staff())
    url = reverse("admin:catalog_stockmovement_changelist")
    html = client.get(url, {"q": order.number}).content.decode()
    assert order.number in html and "Sold" in html
    assert "-3" in html or "−3" in html


def test_nobody_can_add_edit_or_delete_a_line_in_the_admin():
    person = staff()
    request = RequestFactory().get("/")
    request.user = person
    model_admin = admin.site._registry[StockMovement]
    assert not model_admin.has_add_permission(request)
    assert not model_admin.has_change_permission(request)
    assert not model_admin.has_delete_permission(request)
    assert model_admin.has_view_permission(request)
