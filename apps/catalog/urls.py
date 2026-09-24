"""Mounted at the API root (`path("", include(...))`): the catalog owns `products/…` and `content/shop/`.
The frontend writes some of these without a trailing slash, so every route resolves both ways."""
from apps.core.urls import dual_path

from . import views

urlpatterns = [
    *dual_path("products/", views.ProductListView.as_view(), name="product-list"),
    *dual_path("products/new-arrivals/", views.NewArrivalProductsView.as_view(), name="product-new-arrivals"),
    *dual_path("products/best-selling/", views.BestSellingProductsView.as_view(), name="product-best-selling"),
    *dual_path("products/flash-sale/", views.FlashSaleProductsView.as_view(), name="product-flash-sale"),
    *dual_path("products/featured/", views.FeaturedProductsView.as_view(), name="product-featured"),
    *dual_path("products/detail/<slug:slug>/", views.ProductDetailView.as_view(), name="product-detail"),
    *dual_path("products/search-suggestions/", views.SearchSuggestionsView.as_view(), name="search-suggestions"),
    *dual_path("products/categories/", views.AllCategoriesView.as_view(), name="category-list"),
    *dual_path("products/categories/flash-sale/", views.FlashSaleCategoriesView.as_view(), name="category-flash-sale"),
    *dual_path(
        "products/categories/new-arrival/", views.NewArrivalCategoriesView.as_view(), name="category-new-arrival"
    ),
    *dual_path(
        "products/categories/best-selling/", views.BestSellingCategoriesView.as_view(), name="category-best-selling"
    ),
    *dual_path("products/categories/feature/", views.FeaturedCategoriesView.as_view(), name="category-featured"),
    *dual_path("content/shop/", views.ShopContentView.as_view(), name="shop-content"),
]
