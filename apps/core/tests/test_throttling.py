"""The throttle safety net: every view has a generous default limit, the sensitive public writes have a tight scope of
their own, and the client's address is what the reverse proxy saw, not what a header claims."""
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.urls import get_resolver
from rest_framework.permissions import AllowAny
from rest_framework.settings import api_settings
from rest_framework.test import APIRequestFactory
from rest_framework.throttling import BaseThrottle, ScopedRateThrottle, SimpleRateThrottle
from rest_framework.views import APIView

PLAIN = "/api/v1/_t/plain/"  # public, no authentication
PROTECTED = "/api/v1/_t/protected/"  # signed in

WRITE_METHODS = ("post", "put", "patch", "delete")
# Public views that accept writes without a throttle scope of their own, and why that is fine.
UNTHROTTLED_ON_PURPOSE = {
    "ApiNotFoundView": "answers 404 to everything; nothing is read, written or sent",
}


def api_views():
    """Every APIView class reachable from the real URLconf (each once)."""
    found = {}

    def walk(patterns):
        for pattern in patterns:
            if hasattr(pattern, "url_patterns"):
                walk(pattern.url_patterns)
                continue
            view_class = getattr(pattern.callback, "cls", None)
            if view_class is not None and issubclass(view_class, APIView):
                found[view_class] = None

    walk(get_resolver("config.urls").url_patterns)
    return list(found)


# --- the client's address ----------------------------------------------------------------------------------------
def ident(settings, num_proxies, forwarded_for=None, remote="10.0.0.1"):
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "NUM_PROXIES": num_proxies}
    extra = {"REMOTE_ADDR": remote}
    if forwarded_for is not None:
        extra["HTTP_X_FORWARDED_FOR"] = forwarded_for
    return BaseThrottle().get_ident(APIRequestFactory().get("/", **extra))


def test_with_no_proxy_the_forwarded_for_header_is_ignored(settings):
    assert ident(settings, 0, "6.6.6.6, 7.7.7.7") == "10.0.0.1"
    assert ident(settings, 0) == "10.0.0.1"


def test_behind_one_proxy_the_client_is_the_address_that_proxy_appended(settings):
    """`X-Forwarded-For: <what the client claims>, <what the proxy saw>`: only the last one is trustworthy."""
    assert ident(settings, 1, "6.6.6.6, 203.0.113.9") == "203.0.113.9"


def test_behind_two_proxies_it_is_the_second_from_the_right(settings):
    assert ident(settings, 2, "6.6.6.6, 203.0.113.9, 172.16.0.4") == "203.0.113.9"


def test_a_proxy_that_sent_no_header_falls_back_to_the_connection(settings):
    assert ident(settings, 1) == "10.0.0.1"


# --- the default limits ------------------------------------------------------------------------------------------
def test_every_view_falls_back_to_a_generous_default_limit():
    assert [cls.__name__ for cls in api_settings.DEFAULT_THROTTLE_CLASSES] == ["AnonRateThrottle", "UserRateThrottle"]
    for scope in ("anon", "user"):
        assert api_settings.DEFAULT_THROTTLE_RATES[scope]


@pytest.mark.urls("apps.core.tests.urls")
def test_a_guest_over_the_limit_gets_a_429_and_a_new_forwarded_for_header_does_not_help(
    api_client, settings, monkeypatch
):
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "NUM_PROXIES": 0}
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "anon", "3/min")

    responses = [api_client.get(PLAIN, HTTP_X_FORWARDED_FOR=f"9.9.9.{n}") for n in range(5)]

    assert [response.status_code for response in responses] == [200, 200, 200, 429, 429]
    body = responses[-1].json()
    assert body["success"] is False and body["message"] == "Too many requests."
    assert int(responses[-1]["Retry-After"]) > 0


@pytest.mark.urls("apps.core.tests.urls")
def test_a_signed_in_customer_has_a_limit_of_their_own(api_client, monkeypatch):
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "user", "2/min")
    User = get_user_model()

    api_client.force_authenticate(User(pk=1))
    statuses = [api_client.get(PROTECTED).status_code for _ in range(3)]

    assert statuses == [200, 200, 429]
    api_client.force_authenticate(User(pk=2))
    assert api_client.get(PROTECTED).status_code == 200  # somebody else's allowance is untouched


# --- the audit, as a test ----------------------------------------------------------------------------------------
def public_writes():
    """(view class, method) for every view that lets a guest write."""
    for view_class in api_views():
        for method in WRITE_METHODS:
            if not hasattr(view_class, method):
                continue
            view = view_class()
            view.request = SimpleNamespace(method=method.upper())
            if any(isinstance(permission, AllowAny) for permission in view.get_permissions()):
                yield view_class, method, view


def test_the_audit_sees_the_public_writes_it_should():
    names = {view_class.__name__ for view_class, _, _ in public_writes()}
    assert {"RegisterView", "LoginView", "VerifyOTPView"} <= names


def test_every_public_write_has_a_throttle_scope_of_its_own():
    """A new endpoint that lets a guest write must say how often (`throttle_scope`), or be listed above with a reason.
    The generous default is a safety net, not a limit for something that sends an SMS or takes stock."""
    rates = api_settings.DEFAULT_THROTTLE_RATES
    for view_class, method, view in public_writes():
        if view_class.__name__ in UNTHROTTLED_ON_PURPOSE:
            continue
        scoped = [throttle for throttle in view.get_throttles() if isinstance(throttle, ScopedRateThrottle)]
        assert scoped, f"{view_class.__name__}.{method} is open to guests and has no throttle scope"
        assert view.throttle_scope in rates, f"{view_class.__name__}: no rate is configured for {view.throttle_scope!r}"


def test_every_throttle_scope_in_use_has_a_configured_rate():
    """A scope without a rate is an ImproperlyConfigured on the first request that reaches it."""
    for view_class in api_views():
        scope = getattr(view_class, "throttle_scope", None)
        if scope:
            assert scope in api_settings.DEFAULT_THROTTLE_RATES, f"{view_class.__name__} uses the scope {scope!r}"
