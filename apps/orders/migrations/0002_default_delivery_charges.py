from decimal import Decimal

from django.db import migrations

# Business defaults (BDT). The shop owner edits them in the admin (Orders > Delivery charges); an existing row is
# never overwritten, so re-running or re-applying this migration keeps the owner's numbers.
DEFAULTS = {"inside_dhaka": Decimal("60.00"), "outside_dhaka": Decimal("120.00")}


def create_delivery_charges(apps, schema_editor):
    DeliveryCharge = apps.get_model("orders", "DeliveryCharge")
    for shipping_type, amount in DEFAULTS.items():
        DeliveryCharge.objects.get_or_create(shipping_type=shipping_type, defaults={"amount": amount})


class Migration(migrations.Migration):
    dependencies = [("orders", "0001_initial")]

    operations = [migrations.RunPython(create_delivery_charges, migrations.RunPython.noop)]
