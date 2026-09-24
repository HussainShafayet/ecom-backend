from django.db import migrations

# order status -> (payment status, was cash collected)
BY_ORDER_STATUS = {
    "pending": ("pending", False),
    "shipped": ("pending", False),
    "paid": ("paid", True),
    "delivered": ("paid", True),
    "cancelled": ("cancelled", False),
    "refunded": ("refunded", True),  # a refund only follows a paid or delivered order
}


def backfill_payments(apps, schema_editor):
    """Give every order that was placed before this app existed the payment record it would have got: the money side
    is derived from the order's status. Orders that already have one are left alone, so re-running is harmless."""
    Order = apps.get_model("orders", "Order")
    Payment = apps.get_model("payments", "Payment")
    missing = Order.objects.filter(payments__isnull=True)
    payments = []
    for order in missing.iterator():
        status, collected = BY_ORDER_STATUS[order.status]
        payments.append(
            Payment(
                order=order,
                method=order.payment_method,
                status=status,
                amount=order.total,
                paid_at=order.updated_at if collected else None,
                refunded_at=order.updated_at if status == "refunded" else None,
            )
        )
    Payment.objects.bulk_create(payments)


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0002_default_delivery_charges"),
        ("payments", "0001_initial"),
    ]

    operations = [migrations.RunPython(backfill_payments, migrations.RunPython.noop)]
