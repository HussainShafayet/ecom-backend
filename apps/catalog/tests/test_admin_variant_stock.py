"""The product page's variant rows must not write back a stock the shop moved while the page was open: an order takes stock, a return counts
damaged units. The stock box keeps a hidden copy of what it showed (`initial-...`), so a save can tell a typed number from a left-alone one."""
import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory
from django.urls import reverse

from apps.catalog.admin import ProductVariantInline
from apps.catalog.models import Product, ProductVariant, StockMovement
from apps.orders.tests.helpers import line, make_order, stock_of, stocked

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff():
    return get_user_model().objects.create_superuser("+8801700000000", password="s3cret-Pass!", name="Root")


def request_by(staff):
    request = RequestFactory().post("/")
    request.user = staff
    return request


def variant_formset(request, product, variant, shown, posted, **fields):
    """The variant rows as the browser posts them: `shown` is the stock the page displayed when it opened, `posted` what is in the box now."""
    formset_class = ProductVariantInline(Product, admin.site).get_formset(request, product)
    prefix = formset_class.get_default_prefix()
    data = {
        f"{prefix}-TOTAL_FORMS": "1",
        f"{prefix}-INITIAL_FORMS": "1",
        f"{prefix}-MIN_NUM_FORMS": "1",
        f"{prefix}-MAX_NUM_FORMS": "1000",
        f"{prefix}-0-id": str(variant.pk),
        f"{prefix}-0-product": str(product.pk),
        f"{prefix}-0-color": "",
        f"{prefix}-0-size": "",
        f"{prefix}-0-sku": variant.sku,
        f"{prefix}-0-base_price": "",
        f"{prefix}-0-discount_price": "",
        f"{prefix}-0-stock_quantity": str(posted),
        f"initial-{prefix}-0-stock_quantity": str(shown),
        f"{prefix}-0-is_default": "on",
        f"{prefix}-0-is_active": "on",
    }
    data.update({f"{prefix}-0-{name}": value for name, value in fields.items()})
    formset = formset_class(data, instance=product)
    assert formset.is_valid(), formset.errors
    return formset


def save(staff, product, formset):
    admin.site._registry[Product].save_formset(request_by(staff), None, formset, True)


def test_an_untouched_stock_box_does_not_undo_an_order_placed_while_the_page_was_open(staff):
    mug, mug_v = stocked("Mug", stock=10)
    make_order(line(mug, mug_v, 2))  # the page showed 10; the shop has 8 now
    save(staff, mug, variant_formset(request_by(staff), mug, mug_v, shown=10, posted=10, base_price="50.00"))
    mug_v.refresh_from_db()
    assert mug_v.base_price == 50  # what the person did change is saved ...
    assert mug_v.stock_quantity == 8  # ... and the stock is not put back to 10


def test_nothing_changed_at_all_writes_nothing(staff):
    mug, mug_v = stocked("Mug", stock=10)
    make_order(line(mug, mug_v, 2))
    formset = variant_formset(request_by(staff), mug, mug_v, shown=10, posted=10)
    assert not formset.has_changed()
    save(staff, mug, formset)
    assert stock_of(mug_v) == 8


def test_a_stock_the_person_typed_is_written_and_measured_against_the_real_row(staff):
    mug, mug_v = stocked("Mug", stock=10)
    make_order(line(mug, mug_v, 2))
    save(staff, mug, variant_formset(request_by(staff), mug, mug_v, shown=10, posted=12))
    assert stock_of(mug_v) == 12
    entry = StockMovement.objects.filter(variant=mug_v).first()
    assert (entry.kind, entry.change, entry.stock_after, entry.by) == (StockMovement.Kind.MANUAL, 4, 12, staff)  # from the 8 that were there


def test_the_form_never_writes_the_damaged_count_back(staff):
    mug, mug_v = stocked("Mug", stock=10)
    formset = variant_formset(request_by(staff), mug, mug_v, shown=10, posted=11)
    ProductVariant.objects.filter(pk=mug_v.pk).update(damaged_quantity=4)  # a return was received while the page was open
    save(staff, mug, formset)
    mug_v.refresh_from_db()
    assert (mug_v.stock_quantity, mug_v.damaged_quantity) == (11, 4)


def test_the_product_page_carries_the_hidden_copy_of_the_stock(staff):
    mug, mug_v = stocked("Mug", stock=10)
    client = Client()
    client.force_login(staff)
    html = client.get(reverse("admin:catalog_product_change", args=[mug.pk])).content.decode()
    assert 'name="initial-variants-0-stock_quantity"' in html
