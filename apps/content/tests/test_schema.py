import pytest
import yaml
from django.core.management import call_command

from apps.content.models import Page


@pytest.fixture
def schema(tmp_path):
    out = tmp_path / "openapi.yaml"
    call_command("spectacular", file=str(out), validate=True, fail_on_warn=True)
    return yaml.safe_load(out.read_text())


def test_the_pages_endpoint_is_documented_with_the_page_names(schema):
    operation = schema["paths"]["/api/v1/content/pages/{page}/"]["get"]
    page_param = next(param for param in operation["parameters"] if param["name"] == "page")
    assert page_param["in"] == "path"
    assert set(page_param["schema"]["enum"]) == set(Page.values)


def test_the_response_is_the_envelope_around_page_content(schema):
    operation = schema["paths"]["/api/v1/content/pages/{page}/"]["get"]
    body = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert body["required"] == ["success", "message", "data"]
    assert body["properties"]["data"]["$ref"].endswith("/PagePayload")
    content = schema["components"]["schemas"]["PageContent"]
    assert set(content["properties"]) == {"image_sliders", "video_sliders", "left_banner", "right_banner"}
    item = schema["components"]["schemas"]["ContentItem"]
    assert set(item["properties"]) == {"order", "type", "link", "external_link", "media", "media_type", "caption"}
