from decimal import Decimal
from importlib import import_module

import pytest
from django.apps import apps as django_apps
from django.core.management import call_command
from django.db import IntegrityError, transaction

from apps.orders.models import DeliveryCharge, Order, OrderItem, OrderSequence, OrderStatusHistory
from apps.orders.tests.helpers import line, make_order, stocked

pytestmark = pytest.mark.django_db


def bare_order(**kwargs):
    fields = {
        "name": "Rahim",
        "phone_number": "+8801712345678",
        "shipping_type": "inside_dhaka",
        "shipping_area": "Gulshan",
        "shipping_address": "House 1",
        "subtotal": Decimal("100.00"),
        "delivery_charge": Decimal("60.00"),
        "total": Decimal("160.00"),
    }
    fields.update(kwargs)
    return Order.objects.create(**fields)


def bare_item(order, **kwargs):
    fields = {
        "order": order,
        "product_name": "Mug",
        "variant_label": "Default",
        "sku": "MUG",
        "unit_price": Decimal("50.00"),
        "base_price": Decimal("50.00"),
        "quantity": 2,
        "line_total": Decimal("100.00"),
    }
    fields.update(kwargs)
    return OrderItem.objects.create(**fields)


def refused_by_the_database(create):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            create()


# --- the delivery charges migration ---------------------------------------------------------------------------
def test_the_migration_seeds_the_default_delivery_charges():
    migration = import_module("apps.orders.migrations.0002_default_delivery_charges")
    DeliveryCharge.objects.all().delete()

    migration.create_delivery_charges(django_apps, None)

    assert dict(DeliveryCharge.objects.values_list("shipping_type", "amount")) == {
        "inside_dhaka": Decimal("60.00"),
        "outside_dhaka": Decimal("120.00"),
    }


def test_running_the_migration_again_keeps_what_the_owner_changed():
    migration = import_module("apps.orders.migrations.0002_default_delivery_charges")
    DeliveryCharge.objects.filter(shipping_type="inside_dhaka").update(amount=Decimal("75.00"))
    migration.create_delivery_charges(django_apps, None)
    assert DeliveryCharge.objects.get(shipping_type="inside_dhaka").amount == Decimal("75.00")
    assert DeliveryCharge.objects.count() == 2


def test_there_is_one_charge_per_shipping_type():
    refused_by_the_database(lambda: DeliveryCharge.objects.create(shipping_type="inside_dhaka", amount=Decimal("1")))


def test_a_charge_can_not_be_negative():
    refused_by_the_database(lambda: DeliveryCharge.objects.filter(shipping_type="inside_dhaka").update(amount=-1))


# --- constraints of the order tables ----------------------------------------------------------------------------
def test_the_total_must_be_the_subtotal_plus_the_delivery_charge():
    bare_order()  # fine
    refused_by_the_database(lambda: bare_order(total=Decimal("161.00")))


@pytest.mark.parametrize("field", ["subtotal", "delivery_charge"])
def test_order_amounts_can_not_be_negative(field):
    refused_by_the_database(lambda: bare_order(**{field: Decimal("-1.00"), "total": Decimal("59.00")}))


def test_order_numbers_are_unique_but_many_orders_may_still_wait_for_theirs():
    bare_order(number="GC-1")
    bare_order(number=None)
    bare_order(number=None)  # NULLs do not clash: the number is assigned at the end of place_order
    refused_by_the_database(lambda: bare_order(number="GC-1"))


def test_a_line_total_must_be_the_unit_price_times_the_quantity():
    order = bare_order()
    bare_item(order)  # fine
    refused_by_the_database(lambda: bare_item(order, line_total=Decimal("99.99")))


def test_a_line_needs_at_least_one_unit_and_no_negative_price():
    order = bare_order()
    refused_by_the_database(lambda: bare_item(order, quantity=0, line_total=Decimal("0.00")))
    refused_by_the_database(
        lambda: bare_item(order, unit_price=Decimal("-5.00"), line_total=Decimal("-10.00"))
    )
    refused_by_the_database(lambda: bare_item(order, base_price=Decimal("-1.00")))


def test_deleting_an_order_takes_its_lines_and_history():
    product, variant = stocked()
    order = make_order(line(product, variant))
    order.payments.all().delete()  # a payment PROTECTs its order (see apps/payments); without one the rest cascades
    order.delete()
    assert not OrderItem.objects.exists()
    assert not OrderStatusHistory.objects.exists()


# --- catalog cleanup keeps working --------------------------------------------------------------------------------
def test_seed_catalog_flush_still_works_with_orders_in_the_database():
    product, variant = stocked("Mug")
    make_order(line(product, variant))

    call_command("seed_catalog", "--flush", "--products", "1", "--force")

    assert Order.objects.count() == 1
    item = OrderItem.objects.get()
    assert (item.product, item.variant, item.product_name) == (None, None, "Mug")


def test_string_forms_are_readable():
    product, variant = stocked("Mug")
    order = make_order(line(product, variant, 2))
    assert str(order) == order.number
    assert str(bare_order()).startswith("Order #")
    assert str(order.items.get()) == "2 x Mug (Default)"
    assert str(order.history.get()) == f"{order.pk}: new -> pending"
    assert str(DeliveryCharge.objects.get(shipping_type="inside_dhaka")) == "Inside Dhaka: 60.00"
    assert str(OrderSequence.objects.get()).endswith(": 1")
