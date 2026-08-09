from django.urls import path

from . import views

app_name = "verification"

urlpatterns = [
    path("", views.VerificationHomeView.as_view(), name="home"),
    path("selfie/", views.SelfieVerificationView.as_view(), name="selfie"),
    path("identity/", views.IdentityVerificationView.as_view(), name="identity"),
    path("phone/", views.PhoneVerificationView.as_view(), name="phone"),
    path("phone/confirm/", views.PhoneConfirmView.as_view(), name="phone_confirm"),
    path("phone/resend/", views.ResendPhoneCodeView.as_view(), name="phone_resend"),

    # Staff
    path("queue/", views.VerificationQueueView.as_view(), name="queue"),
    path("queue/<uuid:request_id>/decide/", views.VerificationDecideView.as_view(),
         name="decide"),
]
