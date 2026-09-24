"""The React shop's calls (config/frontend_calls.py) against the real URL configuration."""
import pytest
from django.urls import Resolver404, resolve

from apps.core.views import ApiNotFoundView
from config.frontend_calls import FRONTEND_CALLS, api_path

CALLS = [pytest.param(method, template, id=f"{method} {template}") for method, template in FRONTEND_CALLS]


def view_class_for(path):
    match = resolve(path)
    return getattr(match.func, "cls", None)


def test_the_list_has_no_duplicates_and_is_not_empty():
    assert len(FRONTEND_CALLS) == len(set(FRONTEND_CALLS)) > 40


@pytest.mark.parametrize("method, template", CALLS)
def test_the_call_reaches_a_real_view_that_accepts_its_method(method, template):
    path = api_path(template)
    view_class = view_class_for(path)

    assert view_class is not None, f"{path} does not resolve to an API view"
    assert view_class is not ApiNotFoundView, f"{method} {path} falls into the catch-all 404"
    assert hasattr(view_class, method.lower()), f"{view_class.__name__} has no {method}"


@pytest.mark.parametrize("method, template", CALLS)
def test_the_call_resolves_with_and_without_its_trailing_slash(method, template):
    """APPEND_SLASH is off (a redirect would break a CORS preflight), so both spellings must be routes themselves."""
    path = api_path(template)
    other = path.rstrip("/") if path.endswith("/") else path + "/"

    assert view_class_for(path) is view_class_for(other) is not ApiNotFoundView


def test_an_unknown_path_still_falls_into_the_catch_all():
    """The check above is only meaningful if the catch-all really is what unknown paths resolve to."""
    assert view_class_for("/api/v1/definitely/not/a/route/") is ApiNotFoundView


def test_the_test_would_notice_a_missing_route():
    with pytest.raises(Resolver404):
        resolve("/not-under-the-api/")
