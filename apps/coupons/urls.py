"""Mounted at the API root (`path("", include(...))`)."""
from apps.core.urls import dual_path

from . import views

urlpatterns = [
    *dual_path("coupons/validate/", views.CouponValidateView.as_view(), name="coupon-validate"),
]
