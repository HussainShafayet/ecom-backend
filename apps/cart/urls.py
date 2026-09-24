from apps.core.urls import dual_path

from . import views

urlpatterns = [
    *dual_path("cart/", views.CartView.as_view(), name="cart"),
]
