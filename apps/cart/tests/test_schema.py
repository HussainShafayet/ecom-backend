import pytest
import yaml
from django.core.management import call_command


@pytest.fixture
def schema(tmp_path):
    out = tmp_path / "openapi.yaml"
    call_command("spectacular", file=str(out), validate=True, fail_on_warn=True)
    return yaml.safe_load(out.read_text())


def test_cart_and_favourite_are_documented_in_their_canonical_form(schema):
    for path in ("/api/v1/accounts/cart/", "/api/v1/accounts/favourite/"):
        assert set(schema["paths"][path]) == {"get", "post", "put"}, path
    assert "/api/v1/accounts/cart" not in schema["paths"]


def test_the_cart_post_documents_its_fields_and_the_put_takes_an_array(schema):
    post = schema["paths"]["/api/v1/accounts/cart/"]["post"]
    ref = post["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    request = schema["components"]["schemas"][ref.split("/")[-1]]
    assert set(request["properties"]) == {"product_id", "quantity", "variant_id", "action"}
    assert schema["components"]["schemas"]["ActionEnum"]["enum"] == ["increase", "decrease"]
    put_body = schema["paths"]["/api/v1/accounts/cart/"]["put"]["requestBody"]["content"]["application/json"]["schema"]
    assert put_body["type"] == "array"


def test_the_cart_response_is_an_array_of_product_cards_with_the_line_fields(schema):
    body = schema["paths"]["/api/v1/accounts/cart/"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert body["required"] == ["success", "message", "data"]
    assert body["properties"]["data"]["type"] == "array"
    item = schema["components"]["schemas"]["CartItem"]
    line_fields = {"id", "variant_id", "base_price", "discount_price", "quantity", "color_name", "size_name"}
    assert line_fields <= set(item["properties"])
