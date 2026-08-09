"""Likes REST routes, mounted at /api/v1/likes/."""
from django.urls import path

from . import api_views

app_name = "likes"

urlpatterns = [
    path("swipe/", api_views.SwipeAPIView.as_view(), name="swipe"),
    path("rewind/", api_views.RewindAPIView.as_view(), name="rewind"),
    path("quota/", api_views.QuotaAPIView.as_view(), name="quota"),
    path("admirers/count/", api_views.AdmirerCountAPIView.as_view(), name="admirer_count"),
]
