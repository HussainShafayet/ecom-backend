"""Mounted at the API root (`path("", include(...))`): `orders/` and, next to the catalog's and the CMS's,
`content/checkout/`."""
from apps.core.urls import dual_path

from . import views

urlpatterns = [
    *dual_path("orders/", views.OrderListCreateView.as_view(), name="orders"),
    *dual_path("orders/track/", views.OrderTrackingView.as_view(), name="order-track"),  # before <number>
    *dual_path("orders/<slug:number>/", views.OrderDetailView.as_view(), name="order-detail"),
    *dual_path("orders/<slug:number>/cancel/", views.OrderCancelView.as_view(), name="order-cancel"),
    *dual_path("content/checkout/", views.CheckoutContentView.as_view(), name="checkout-content"),
]
