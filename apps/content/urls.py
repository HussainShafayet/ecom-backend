"""Mounted at the API root (`path("", include(...))`) next to the catalog, which owns `content/shop/`."""
from apps.core.urls import dual_path

from . import views

urlpatterns = [
    *dual_path("content/pages/<slug:page>/", views.PageContentView.as_view(), name="page-content"),
]
