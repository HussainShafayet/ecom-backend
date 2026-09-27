"""Mounted at the API root (`path("", include(...))`): everything the storefront shows that is not a product."""
from apps.core.urls import dual_path

from . import views

urlpatterns = [
    *dual_path("site/", views.SiteView.as_view(), name="site"),
    *dual_path("site/pages/<slug:slug>/", views.StaticPageView.as_view(), name="site-page"),
    *dual_path("site/faq/", views.FaqView.as_view(), name="site-faq"),
    *dual_path("site/contact/", views.ContactView.as_view(), name="site-contact"),
    *dual_path("site/newsletter/", views.NewsletterView.as_view(), name="site-newsletter"),
]
