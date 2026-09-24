import pytest
import yaml
from django.core.management import call_command

REVIEWS = "/api/v1/products/reviews/"
ONE = "/api/v1/products/reviews/{id}/"


@pytest.fixture
def schema(tmp_path):
    out = tmp_path / "openapi.yaml"
    call_command("spectacular", file=str(out), validate=True, fail_on_warn=True)
    return yaml.safe_load(out.read_text())


def component(schema, ref):
    return schema["components"]["schemas"][ref.split("/")[-1]]


def test_the_endpoints_are_documented_in_their_canonical_form(schema):
    assert set(schema["paths"][REVIEWS]) == {"get", "post"}
    assert set(schema["paths"][ONE]) == {"put"}
    assert "/api/v1/products/reviews" not in schema["paths"]


def test_reading_is_public_and_writing_needs_a_token(schema):
    assert {} in schema["paths"][REVIEWS]["get"]["security"]  # anonymous allowed
    assert schema["paths"][REVIEWS]["post"]["security"] == [{"jwtAuth": []}]
    assert schema["paths"][ONE]["put"]["security"] == [{"jwtAuth": []}]


def test_the_list_documents_can_review_and_the_review_shape(schema):
    get = schema["paths"][REVIEWS]["get"]
    (param,) = get["parameters"]
    assert (param["name"], param["required"]) == ("product_id", True)
    page = component(schema, get["responses"]["200"]["content"]["application/json"]["schema"]["properties"]["data"]["$ref"])
    assert set(page["properties"]) == {"count", "next", "previous", "results", "can_review", "review_status", "order_id"}
    assert page["properties"]["order_id"]["nullable"] is True  # only with waiting_for_delivery
    status = component(schema, page["properties"]["review_status"]["allOf"][0]["$ref"])
    assert status["enum"] == ["can_review", "reviewed", "waiting_for_delivery", "not_purchased", "guest"]
    review = component(schema, page["properties"]["results"]["items"]["$ref"])
    assert set(review["properties"]) == {
        "id",
        "product_id",
        "user_name",
        "rating",
        "comment",
        "created_at",
        "can_edited",
        "media_urls",
    }
    assert set(review["required"]) == set(review["properties"])
    media = component(schema, review["properties"]["media_urls"]["items"]["$ref"])
    assert set(media["properties"]) == {"file", "type"}


def test_writing_is_documented_as_multipart_with_repeated_files(schema):
    body = schema["paths"][REVIEWS]["post"]["requestBody"]["content"]
    assert set(body) == {"multipart/form-data"}
    request = component(schema, body["multipart/form-data"]["schema"]["$ref"])
    assert set(request["required"]) == {"product_id", "rating", "comment"}
    assert request["properties"]["media"]["type"] == "array"
    assert request["properties"]["media"]["items"] == {"type": "string", "format": "binary"}


def test_editing_makes_every_field_optional(schema):
    body = schema["paths"][ONE]["put"]["requestBody"]["content"]["multipart/form-data"]["schema"]["$ref"]
    request = component(schema, body)
    assert set(request["properties"]) == {"product_id", "rating", "comment", "media"}
    assert not request.get("required")
