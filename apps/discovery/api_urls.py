"""Discovery REST routes, mounted at /api/v1/discovery/."""
from django.urls import path

from . import api_views

app_name = "discovery"

urlpatterns = [
    path("", api_views.FeedAPIView.as_view(), name="feed"),
    path("admirers/", api_views.AdmirersAPIView.as_view(), name="admirers"),
]
