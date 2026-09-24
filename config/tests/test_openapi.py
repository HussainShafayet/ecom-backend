"""`openapi.yaml` is the schema the frontend team reads: it must be the schema the code produces, and it must
document every call the React shop makes."""
import re
from pathlib import Path

import pytest
import yaml
from django.core.management import call_command

from config.frontend_calls import FRONTEND_CALLS, api_path

SCHEMA_FILE = Path(__file__).resolve().parents[2] / "openapi.yaml"
REGENERATE = "python manage.py spectacular --file openapi.yaml --validate --fail-on-warn"


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    target = tmp_path_factory.mktemp("schema") / "openapi.yaml"
    call_command("spectacular", file=str(target), validate=True, fail_on_warn=True)
    return target.read_text()


def test_openapi_yaml_is_what_the_code_generates(generated):
    assert SCHEMA_FILE.read_text() == generated, f"openapi.yaml is stale. Regenerate it: {REGENERATE}"


def documented_operation(paths, concrete_path, method):
    """The schema's operation for a concrete path such as /api/v1/content/pages/home/, or None. A templated path
    (`/content/pages/{page}/`) matches when the value fits the parameter's `enum`, if it has one."""
    for template, operations in paths.items():
        pieces = re.split(r"\{([^}]+)\}", template)  # literal, name, literal, name, ..., literal
        regex = "".join(re.escape(piece) if index % 2 == 0 else "([^/]+)" for index, piece in enumerate(pieces))
        match = re.fullmatch(regex, concrete_path)
        operation = operations.get(method.lower())
        if not match or operation is None:
            continue
        values = dict(zip(pieces[1::2], match.groups()))
        parameters = {p["name"]: p for p in operation.get("parameters", []) if p["in"] == "path"}
        if all(value in parameters.get(name, {}).get("schema", {}).get("enum", [value]) for name, value in values.items()):
            return operation
    return None


@pytest.mark.parametrize("method, template", FRONTEND_CALLS, ids=[f"{m} {t}" for m, t in FRONTEND_CALLS])
def test_every_call_of_the_frontend_is_in_the_schema(method, template):
    paths = yaml.safe_load(SCHEMA_FILE.read_text())["paths"]
    concrete = api_path(template).rstrip("/") + "/"  # the schema lists each route once, with its trailing slash

    assert documented_operation(paths, concrete, method), f"{method} {concrete} is not documented in openapi.yaml"


def test_the_matcher_rejects_a_page_that_is_not_in_the_enum():
    paths = yaml.safe_load(SCHEMA_FILE.read_text())["paths"]
    assert documented_operation(paths, "/api/v1/content/pages/home/", "GET")
    assert documented_operation(paths, "/api/v1/content/pages/nonexistent/", "GET") is None
    assert documented_operation(paths, "/api/v1/accounts/cart/", "PATCH") is None
