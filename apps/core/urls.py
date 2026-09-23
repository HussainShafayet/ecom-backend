from django.urls import path


def dual_path(route, view, kwargs=None, name=None):
    """Register `route` with AND without its trailing slash.

    The frontend mixes `/products?...`, `/products/detail/x` and `/accounts/cart/`. With APPEND_SLASH off
    (a 301 breaks CORS preflights that carry Authorization) both spellings must resolve directly.
    Use it inside `urlpatterns` with unpacking:  `*dual_path("cart/", CartView.as_view(), name="cart")`.
    `route` must end with "/" (the canonical form, also the one documented in the OpenAPI schema).
    """
    if not route.endswith("/") or route == "/":
        raise ValueError("dual_path() needs a non-empty route ending with '/'")
    return [
        path(route, view, kwargs, name=name),
        path(route.rstrip("/"), view, kwargs),
    ]
