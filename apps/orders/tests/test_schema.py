import pytest
import yaml
from django.core.management import call_command

ORDERS = "/api/v1/orders/"
ORDER = "/api/v1/orders/{number}/"
CANCEL = "/api/v1/orders/{number}/cancel/"
TRACK = "/api/v1/orders/track/"
CHECKOUT = "/api/v1/content/checkout/"


@pytest.fixture
def schema(tmp_path):
    out = tmp_path / "openapi.yaml"
    call_command("spectacular", file=str(out), validate=True, fail_on_warn=True)
    return yaml.safe_load(out.read_text())


def component(schema, name):
    return schema["components"]["schemas"][name]


def test_the_endpoints_are_documented_in_their_canonical_form(schema):
    assert set(schema["paths"][ORDERS]) == {"get", "post"}  # my orders / place an order
    assert set(schema["paths"][ORDER]) == {"get"}
    assert set(schema["paths"][CANCEL]) == {"post"}
    assert set(schema["paths"][TRACK]) == {"get"}
    assert set(schema["paths"][CHECKOUT]) == {"get"}
    assert "/api/v1/orders" not in schema["paths"] and "/api/v1/content/checkout" not in schema["paths"]


def test_placing_an_order_documents_the_body_and_the_created_response(schema):
    post = schema["paths"][ORDERS]["post"]
    ref = post["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    request = component(schema, ref.split("/")[-1])
    assert set(request["properties"]) == {
        "name",
        "email",
        "phone_number",
        "shipping_type",
        "shipping_area",
        "shipping_division",
        "shipping_district",
        "shipping_thana",
        "shipping_address",
        "payment_type",
        "items",
    }
    assert set(request["required"]) == {"name", "phone_number", "shipping_type", "shipping_address", "items"}
    assert component(schema, "PaymentTypeEnum")["enum"] == ["cash", "cod"]
    assert component(schema, "ShippingTypeEnum")["enum"] == ["inside_dhaka", "outside_dhaka"]
    item = component(schema, "OrderItemInputRequest")
    assert set(item["properties"]) == {"product_id", "variant_id", "quantity"}  # no price: it is ignored
    assert set(item["required"]) == {"product_id", "quantity"}

    assert "201" in post["responses"] and "200" not in post["responses"]
    body = post["responses"]["201"]["content"]["application/json"]["schema"]
    assert body["required"] == ["success", "message", "data"]
    assert set(component(schema, "OrderPlaced")["properties"]) == {
        "order_id", "status", "created_at", "subtotal", "delivery_charge", "total"
    }
    assert component(schema, "OrderPlaced")["properties"]["order_id"]["type"] == "string"
    assert component(schema, "OrderPlaced")["properties"]["total"]["type"] == "number"  # a number, not a string


def test_placing_an_order_is_open_to_guests_and_bearer_tokens(schema):
    security = schema["paths"][ORDERS]["post"]["security"]
    assert {} in security and {"jwtAuth": []} in security  # both work; a bad token is a 401


def test_the_checkout_content_documents_numbers_and_the_guest_shape(schema):
    security = schema["paths"][CHECKOUT]["get"]["security"]
    assert {} in security and {"jwtAuth": []} in security
    content = component(schema, "CheckoutContent")
    assert set(content["properties"]) == {"delivery_charges", "shipping_addresses", "user_info"}
    assert content["properties"]["user_info"]["nullable"] is True
    assert content["properties"]["shipping_addresses"]["type"] == "array"
    charges = component(schema, "DeliveryCharges")["properties"]
    assert set(charges) == {"inside_dhaka", "outside_dhaka"}
    assert all(prop["type"] == "number" for prop in charges.values())  # numbers, not strings
    assert component(schema, "UserInfo")["properties"]["phone_number"]["type"] == "string"


# --- reading, cancelling and tracking ------------------------------------------------------------------------------
def test_my_orders_and_one_order_need_a_token_and_a_guest_can_place_and_track(schema):
    assert schema["paths"][ORDERS]["get"]["security"] == [{"jwtAuth": []}]
    assert schema["paths"][ORDER]["get"]["security"] == [{"jwtAuth": []}]
    assert schema["paths"][CANCEL]["post"]["security"] == [{"jwtAuth": []}]
    assert "security" not in schema["paths"][TRACK]["get"]  # public: nobody is asked to sign in (like /health/)
    assert schema["paths"][ORDERS]["get"]["operationId"] == "orders_list"


def test_the_order_shapes_are_documented(schema):
    summary = component(schema, "OrderSummary")["properties"]
    assert set(summary) == {"order_id", "status", "status_display", "created_at", "total", "items_count", "items"}
    assert summary["total"]["type"] == "number" and summary["items_count"]["type"] == "integer"
    detail = component(schema, "OrderDetail")["properties"]
    assert {"name", "email", "phone_number", "shipping_address", "subtotal", "delivery_charge", "payment", "history", "can_cancel"} <= set(detail)
    assert detail["can_cancel"]["type"] == "boolean"
    tracking = component(schema, "OrderTracking")["properties"]
    assert not {"name", "email", "phone_number", "shipping_address", "can_cancel"} & set(tracking)  # nothing about who or where
    assert set(component(schema, "OrderStep")["properties"]) == {"status", "status_display", "created_at"}
    item = component(schema, "OrderItem")["properties"]
    assert {"product_id", "product_slug", "product_name", "variant_label", "unit_price", "quantity", "line_total", "image"} <= set(item)


def test_tracking_takes_the_number_and_the_phone_as_query_parameters(schema):
    parameters = {p["name"]: p for p in schema["paths"][TRACK]["get"]["parameters"]}
    assert set(parameters) == {"order_id", "phone_number"}
    assert all(p["in"] == "query" and p["required"] for p in parameters.values())
