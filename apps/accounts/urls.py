from apps.core.urls import dual_path

from . import views

urlpatterns = [
    *dual_path("register/", views.RegisterView.as_view(), name="register"),
    *dual_path("login/", views.LoginView.as_view(), name="login"),
    *dual_path("verify-otp/", views.VerifyOTPView.as_view(), name="verify-otp"),
    *dual_path("resend-otp/", views.ResendOTPView.as_view(), name="resend-otp"),
    *dual_path("token/refresh/", views.TokenRefreshView.as_view(), name="token-refresh"),
    *dual_path("logout/", views.LogoutView.as_view(), name="logout"),
]
