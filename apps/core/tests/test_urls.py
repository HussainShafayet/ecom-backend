import pytest
from django.urls import resolve, reverse

from apps.core.urls import dual_path
from apps.core.views import HealthView

pytestmark = pytest.mark.urls("apps.core.tests.urls")


def test_both_slash_forms_resolve_to_the_same_view():
    with_slash = resolve("/api/v1/_t/dual/")
    without_slash = resolve("/api/v1/_t/dual")
    assert with_slash.func.view_class is without_slash.func.view_class
    assert reverse("dual") == "/api/v1/_t/dual/"


def test_both_slash_forms_answer_directly_without_redirect(api_client):
    for url in ("/api/v1/_t/dual/", "/api/v1/_t/dual"):
        response = api_client.get(url)
        assert response.status_code == 200, url  # a 301 here would break CORS preflights


@pytest.mark.parametrize("bad_route", ["no-trailing-slash", "/"])
def test_dual_path_rejects_routes_that_are_not_canonical(bad_route):
    with pytest.raises(ValueError):
        dual_path(bad_route, HealthView.as_view())


@pytest.mark.urls("config.urls")
def test_real_health_route_has_both_forms():
    assert resolve("/api/v1/health/").func.view_class is HealthView
    assert resolve("/api/v1/health").func.view_class is HealthView
