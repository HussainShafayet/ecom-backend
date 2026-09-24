"""Every API call the React shop makes, spelled the way `ecom/src` writes it (a leading slash or none, a trailing slash
or none). `{id}` and `{slug}` stand for a value; query strings are left out.

Two things read this list: `config/tests/test_frontend_endpoints.py` (every call must reach a real view that accepts
the method) and `scripts/e2e_smoke.py` (drives every call against a running server). When the frontend gains or
changes a call, change it here first: a red test is the reminder that the backend must follow (docs/API_CONTRACT.md).
"""

FRONTEND_CALLS = [
    # products (services/productService.js, redux/slice/productSlice.js)
    ("GET", "/products"),
    ("GET", "/products/new-arrivals"),
    ("GET", "/products/best-selling"),
    ("GET", "/products/flash-sale"),
    ("GET", "/products/featured"),
    ("GET", "/products/detail/{slug}"),
    ("GET", "/products/search-suggestions/"),
    # categories (services/categoryService.js)
    ("GET", "/products/categories"),
    ("GET", "/products/categories/flash-sale/"),
    ("GET", "/products/categories/new-arrival/"),
    ("GET", "/products/categories/best-selling/"),
    ("GET", "/products/categories/feature/"),
    # content (services/contentService.js, redux/slice/checkoutSlice.js)
    ("GET", "/content/pages/home"),
    ("GET", "/content/pages/newarrival/"),
    ("GET", "/content/pages/flashsale"),
    ("GET", "/content/pages/best_selling"),
    ("GET", "/content/pages/feature"),
    ("GET", "/content/pages/category"),
    ("GET", "/content/shop"),
    ("GET", "/content/checkout/"),
    # orders (redux/slice/checkoutSlice.js, redux/slice/orderSlice.js)
    ("POST", "/orders/"),
    ("GET", "/orders/"),
    ("GET", "/orders/{number}/"),
    ("POST", "/orders/{number}/cancel/"),
    ("GET", "/orders/track/"),
    # auth (redux/slice/authSlice.js)
    ("POST", "/accounts/register/"),
    ("POST", "/accounts/verify-otp/"),
    ("POST", "/accounts/resend-otp/"),
    ("POST", "/accounts/login/"),
    ("POST", "accounts/token/refresh/"),
    ("POST", "accounts/logout/"),
    # profile and addresses (redux/slice/profileSlice.js)
    ("GET", "/accounts/profile/"),
    ("PUT", "/accounts/profile/"),
    ("GET", "/accounts/addresses/"),
    ("POST", "/accounts/addresses/"),
    ("PUT", "/accounts/addresses/{id}/"),
    ("DELETE", "/accounts/addresses/{id}/"),
    ("POST", "accounts/request-otp/"),
    ("POST", "accounts/verify-otp-for-profile/"),
    # cart and wishlist (redux/slice/cartSlice.js, redux/slice/wishlistSlice.js)
    ("GET", "/accounts/cart/"),
    ("POST", "/accounts/cart/"),
    ("PUT", "/accounts/cart/"),
    ("GET", "/accounts/favourite/"),
    ("POST", "/accounts/favourite/"),
    ("PUT", "/accounts/favourite/"),
    # reviews (redux/slice/reviewSlice.js)
    ("GET", "products/reviews/"),
    ("POST", "products/reviews/"),
    ("PUT", "products/reviews/{id}/"),
]

SAMPLE_VALUES = {"id": "1", "slug": "a-product", "number": "GC-20260101-0001"}


def api_path(template, api_root="/api/v1/", **values):
    """The path a call is made to: the frontend joins its base URL and the call (a doubled slash collapses)."""
    filled = template.format(**{**SAMPLE_VALUES, **values})
    return api_root.rstrip("/") + "/" + filled.lstrip("/")
