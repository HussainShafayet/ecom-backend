from apps.core.urls import dual_path

from . import views

urlpatterns = [
    *dual_path("addresses/", views.AddressListCreateView.as_view(), name="address-list"),
    *dual_path("addresses/<int:pk>/", views.AddressDetailView.as_view(), name="address-detail"),
]
