from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

# Django's own 404/500 pages are replaced by JSON envelopes for anything under /api/.
handler404 = "apps.core.views.api_not_found"
handler500 = "apps.core.views.api_server_error"

urlpatterns = [
    path("admin/", admin.site.urls),
    # API root: the frontend's VITE_BASE_URL points here (with the trailing slash).
    path("api/v1/", include("config.api_urls")),
]

if settings.ENABLE_API_DOCS:
    urlpatterns += [
        path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
        path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    ]
