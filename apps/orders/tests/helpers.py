"""Shared by the orders tests. `checkout_body` is what the frontend's Checkout page posts."""
from decimal import Decimal

from apps.cart.tests.helpers import lines, signed_in, stocked, with_options  # noqa: F401  (re-exported for the tests)
from apps.orders import services
from apps.orders.models import DeliveryCharge
from apps.orders.serializers import PlaceOrderSerializer

ORDERS = "/api/v1/orders/"
CHECKOUT = "/api/v1/content/checkout/"
DEFAULT_PHONE = "+8801712345678"


def set_charges(inside="60.00", outside="120.00"):
    for shipping_type, amount in (("inside_dhaka", inside), ("outside_dhaka", outside)):
        DeliveryCharge.objects.update_or_create(shipping_type=shipping_type, defaults={"amount": Decimal(amount)})


def line(product, variant=None, quantity=1, **extra):
    """One entry of `items`. The frontend also sends the `price` it shows: pass `price=` to check it is ignored."""
    item = {"product_id": product.pk, "quantity": quantity, **extra}
    if variant is not None:
        item["variant_id"] = variant.pk
    return item


def checkout_body(*items, **overrides):
    """The body of the Checkout page for an order inside Dhaka paid in cash; `overrides` replace any key."""
    body = {
        "name": "Rahim Uddin",
        "email": "",
        "phone_number": DEFAULT_PHONE,
        "shipping_type": "inside_dhaka",
        "shipping_area": "Gulshan",
        "shipping": None,
        "shipping_division": "",
        "shipping_district": "",
        "shipping_thana": "",
        "shipping_address": "House 12, Road 5",
        "payment_type": "cash",
        "items": list(items),
        "sub_total_price": "0.00",
        "delivery_charge": 60,
        "total_price": "0.00",
    }
    body.update(overrides)
    return body


def place(client, *items, **overrides):
    return client.post(ORDERS, checkout_body(*items, **overrides), format="json")


def errors_of(response):
    """The `errors` list of a 400."""
    assert response.status_code == 400, response.content
    body = response.json()
    assert body["success"] is False
    return body["errors"]


def make_order(*items, user=None, **overrides):
    """Place an order through the service, like the view does (for tests that are not about the API)."""
    serializer = PlaceOrderSerializer(data=checkout_body(*items, **overrides))
    serializer.is_valid(raise_exception=True)
    return services.place_order(user=user, data=serializer.validated_data)


def stock_of(variant):
    variant.refresh_from_db()
    return variant.stock_quantity


def orders_of(product):
    product.refresh_from_db()
    return product.total_orders
