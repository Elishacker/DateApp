"""Moderation REST routes, mounted at /api/v1/moderation/."""
from django.urls import path

from . import api_views

app_name = "moderation"

urlpatterns = [
    path("queue/", api_views.ModerationQueueAPIView.as_view(), name="queue"),
    path("screen/", api_views.ScreenTextAPIView.as_view(), name="screen"),
    path("trust/<uuid:user_id>/", api_views.TrustScoreAPIView.as_view(), name="trust"),
]
