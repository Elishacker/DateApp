"""Verification REST routes, mounted at /api/v1/verification/."""
from django.urls import path

from . import api_views

app_name = "verification"

urlpatterns = [
    path("", api_views.VerificationStatusAPIView.as_view(), name="status"),
    path("selfie/", api_views.SelfieUploadAPIView.as_view(), name="selfie"),
    path("phone/", api_views.PhoneVerificationAPIView.as_view(), name="phone"),
    path("queue/", api_views.VerificationQueueAPIView.as_view(), name="queue"),
]
