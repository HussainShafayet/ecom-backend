"""Everything mounted under /api/v1/. New apps add their `include(...)` here, ABOVE the catch-all."""
from django.urls import include, path, re_path

from apps.core.urls import dual_path
from apps.core.views import ApiNotFoundView, HealthView

urlpatterns = [
    *dual_path("health/", HealthView.as_view(), name="health"),
    path("accounts/", include("apps.accounts.urls")),
    path("accounts/", include("apps.addresses.urls")),  # /accounts/addresses/
    path("", include("apps.catalog.urls")),  # /products/…, /content/shop/
    # Keep last: unknown API paths answer with the JSON error envelope (also when DEBUG=True).
    re_path(r"^.*$", ApiNotFoundView.as_view()),
]
