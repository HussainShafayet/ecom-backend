import pytest
import yaml
from django.core.management import call_command


@pytest.fixture
def schema(tmp_path):
    out = tmp_path / "openapi.yaml"
    call_command("spectacular", file=str(out), validate=True, fail_on_warn=True)
    return yaml.safe_load(out.read_text())


def operation(schema, path, method):
    return schema["paths"][path][method]


def data_ref(op, status="200"):
    body = op["responses"][status]["content"]["application/json"]["schema"]
    assert body["required"] == ["success", "message", "data"]
    return body["properties"]["data"]["$ref"].rsplit("/", 1)[-1]


@pytest.mark.parametrize(
    "path, component",
    [
        ("/api/v1/site/", "SitePayload"),
        ("/api/v1/site/pages/{slug}/", "StaticPagePayload"),
        ("/api/v1/site/faq/", "FaqPayload"),
    ],
)
def test_the_reads_are_documented_as_public_envelopes(schema, path, component):
    op = operation(schema, path, "get")
    assert data_ref(op) == component
    assert op["tags"] == ["site"]
    assert "security" not in op  # no token needed, and a stale one is ignored


def test_the_site_shape_is_documented(schema):
    components = schema["components"]["schemas"]
    assert set(components["Site"]["properties"]) == {
        "name", "tagline", "logo", "announcement", "contact", "social_links", "trust_badges", "footer_pages",
    }
    assert set(components["Announcement"]["properties"]) == {"text", "link", "ends_in_seconds"}
    assert components["Announcement"]["properties"]["ends_in_seconds"]["nullable"] is True
    assert set(components["ContactDetails"]["properties"]) == {"email", "phone", "address", "opening_hours", "map_url"}
    assert set(components["FooterPages"]["properties"]) == {"company", "service", "legal"}
    assert components["SocialLink"]["properties"]["platform"]["$ref"].endswith("/PlatformEnum")
    assert set(components["PlatformEnum"]["enum"]) == {
        "facebook", "instagram", "x", "youtube", "linkedin", "tiktok", "whatsapp", "telegram",
    }
    assert set(components["TrustBadge"]["properties"]) == {"icon", "title", "subtitle"}
    assert components["TrustBadge"]["properties"]["icon"]["$ref"].endswith("/IconEnum")
    assert set(components["IconEnum"]["enum"]) == {
        "delivery", "returns", "secure_payment", "cash_on_delivery", "support", "warranty",
    }


def test_the_writes_are_documented_with_their_bodies(schema):
    contact = operation(schema, "/api/v1/site/contact/", "post")
    assert "201" in contact["responses"] and "security" not in contact
    body = schema["components"]["schemas"][contact["requestBody"]["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]]
    assert set(body["properties"]) == {"name", "email", "phone", "subject", "message"}
    assert set(body["required"]) == {"name", "email", "message"}
    newsletter = operation(schema, "/api/v1/site/newsletter/", "post")
    assert "200" in newsletter["responses"] and "security" not in newsletter
