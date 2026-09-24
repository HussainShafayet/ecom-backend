"""Mounted at the API root (`path("", include(...))`): `orders/` and, next to the catalog's and the CMS's,
`content/checkout/`."""
from apps.core.urls import dual_path

from . import views

urlpatterns = [
    *dual_path("orders/", views.PlaceOrderView.as_view(), name="orders"),
    *dual_path("content/checkout/", views.CheckoutContentView.as_view(), name="checkout-content"),
]
