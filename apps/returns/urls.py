"""Mounted at the API root (`path("", include(...))`): the return requests of an order, next to `orders/<number>/`."""
from apps.core.urls import dual_path

from . import views

urlpatterns = [
    *dual_path("orders/<slug:number>/returns/", views.OrderReturnCreateView.as_view(), name="order-return-create"),
    *dual_path(
        "orders/<slug:number>/returns/<int:request_id>/cancel/", views.OrderReturnCancelView.as_view(), name="order-return-cancel"
    ),
]
