from apps.core.urls import dual_path

from . import views

urlpatterns = [
    *dual_path("favourite/", views.FavouriteView.as_view(), name="favourite"),
]
