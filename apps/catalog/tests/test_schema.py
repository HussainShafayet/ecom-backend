import pytest
import yaml
from django.core.management import call_command

from apps.catalog.filters import ProductQuerySerializer


@pytest.fixture
def schema(tmp_path):
    out = tmp_path / "openapi.yaml"
    call_command("spectacular", file=str(out), validate=True, fail_on_warn=True)
    return yaml.safe_load(out.read_text())


CATALOG_PATHS = [
    "/api/v1/products/",
    "/api/v1/products/new-arrivals/",
    "/api/v1/products/best-selling/",
    "/api/v1/products/flash-sale/",
    "/api/v1/products/featured/",
    "/api/v1/products/detail/{slug}/",
    "/api/v1/products/search-suggestions/",
    "/api/v1/products/categories/",
    "/api/v1/products/categories/flash-sale/",
    "/api/v1/products/categories/new-arrival/",
    "/api/v1/products/categories/best-selling/",
    "/api/v1/products/categories/feature/",
    "/api/v1/content/shop/",
]


def test_every_catalog_endpoint_is_documented_in_its_canonical_form(schema):
    assert set(CATALOG_PATHS) <= set(schema["paths"])
    assert not [path for path in schema["paths"] if path.startswith("/api/v1/products") and not path.endswith("/")]


def test_the_product_list_documents_every_query_parameter(schema):
    documented = {param["name"] for param in schema["paths"]["/api/v1/products/"]["get"]["parameters"]}
    assert set(ProductQuerySerializer().fields) | {"page", "page_size"} <= documented


def test_detail_leaves_colors_and_sizes_optional_because_they_can_be_absent(schema):
    required = set(schema["components"]["schemas"]["ProductDetail"]["required"])
    assert {"brand", "media_files", "categories", "variant_id"} <= required
    assert not {"colors", "sizes"} & required


def test_lists_are_paginated_and_wrapped_in_the_envelope(schema):
    body = schema["paths"]["/api/v1/products/"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert body["required"] == ["success", "message", "data"]
