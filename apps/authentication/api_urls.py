"""Authentication REST routes, mounted at /api/v1/auth/."""
from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView

from . import api_views

app_name = "authentication"

urlpatterns = [
    path("register/", api_views.RegisterAPIView.as_view(), name="register"),
    path("login/", api_views.LoginAPIView.as_view(), name="login"),
    path("login/mfa/", api_views.MFALoginAPIView.as_view(), name="login_mfa"),
    path("logout/", api_views.LogoutAPIView.as_view(), name="logout"),
    path("social/", api_views.SocialLoginAPIView.as_view(), name="social"),

    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("token/verify/", TokenVerifyView.as_view(), name="token_verify"),

    path("email/verify/", api_views.VerifyEmailAPIView.as_view(), name="verify_email"),
    path("email/resend/", api_views.ResendVerificationAPIView.as_view(), name="resend_verification"),

    path("password/forgot/", api_views.PasswordResetRequestAPIView.as_view(), name="password_reset"),
    path("password/reset/", api_views.PasswordResetAPIView.as_view(), name="password_reset_confirm"),
    path("password/change/", api_views.PasswordChangeAPIView.as_view(), name="password_change"),

    path("mfa/setup/", api_views.MFASetupAPIView.as_view(), name="mfa_setup"),
    path("mfa/confirm/", api_views.MFAConfirmAPIView.as_view(), name="mfa_confirm"),
    path("mfa/disable/", api_views.MFADisableAPIView.as_view(), name="mfa_disable"),

    path("sessions/", api_views.SessionListAPIView.as_view(), name="sessions"),
]
