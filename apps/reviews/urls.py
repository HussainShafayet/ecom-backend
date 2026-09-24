"""Mounted at the API root: reviews live under `products/reviews/`. The frontend calls these with a trailing slash,
but every route resolves both ways."""
from apps.core.urls import dual_path

from . import views

urlpatterns = [
    *dual_path("products/reviews/", views.ReviewListCreateView.as_view(), name="review-list"),
    *dual_path("products/reviews/<int:pk>/", views.ReviewDetailView.as_view(), name="review-detail"),
]
