"""Notifications REST routes, mounted at /api/v1/notifications/."""
from django.urls import path

from . import api_views

app_name = "notifications"

urlpatterns = [
    path("", api_views.NotificationListView.as_view(), name="list"),
    path("badges/", api_views.BadgeCountView.as_view(), name="badges"),
]
