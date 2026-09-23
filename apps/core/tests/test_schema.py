import pytest
import yaml
from django.core.management import call_command


@pytest.fixture
def schema(tmp_path):
    out = tmp_path / "openapi.yaml"
    # --validate checks the document against the OpenAPI 3 spec; --fail-on-warn keeps the schema clean.
    call_command("spectacular", file=str(out), validate=True, fail_on_warn=True)
    return yaml.safe_load(out.read_text())


def test_health_is_documented_once_in_its_canonical_form(schema):
    assert "/api/v1/health/" in schema["paths"]
    assert "/api/v1/health" not in schema["paths"]  # slashless alias is hidden from the docs


def test_success_responses_are_wrapped_in_the_envelope(schema):
    ok = schema["paths"]["/api/v1/health/"]["get"]["responses"]["200"]
    body = ok["content"]["application/json"]["schema"]
    assert body["required"] == ["success", "message", "data"]
    assert body["properties"]["data"]["$ref"] == "#/components/schemas/Health"


def test_error_envelope_is_documented_for_every_operation(schema):
    responses = schema["paths"]["/api/v1/health/"]["get"]["responses"]
    assert responses["4XX"]["content"]["application/json"]["schema"]["$ref"].endswith("ErrorEnvelope")
    assert "ErrorEnvelope" in schema["components"]["schemas"]
