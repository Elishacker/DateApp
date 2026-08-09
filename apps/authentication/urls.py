from django.urls import path

from . import views

app_name = "authentication"

urlpatterns = [
    path("register/", views.RegisterView.as_view(), name="register"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),

    path("mfa/", views.MFAChallengeView.as_view(), name="mfa_challenge"),
    path("mfa/setup/", views.MFASetupView.as_view(), name="mfa_setup"),
    path("mfa/recovery-codes/", views.MFARecoveryCodesView.as_view(), name="mfa_recovery"),
    path("mfa/disable/", views.MFADisableView.as_view(), name="mfa_disable"),

    path("verify-email/", views.VerifyEmailNoticeView.as_view(), name="verify_email_notice"),
    path("verify-email/resend/", views.ResendVerificationView.as_view(), name="resend_verification"),
    path("verify-email/<str:token>/", views.VerifyEmailView.as_view(), name="verify_email"),

    path("password/forgot/", views.PasswordResetRequestView.as_view(), name="password_reset"),
    path("password/sent/", views.PasswordResetSentView.as_view(), name="password_reset_sent"),
    path("password/reset/<str:token>/", views.PasswordResetConfirmView.as_view(),
         name="password_reset_confirm"),
    path("password/change/", views.PasswordChangeView.as_view(), name="password_change"),

    path("security/", views.security_overview, name="security_overview"),
]
