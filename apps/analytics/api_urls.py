"""Analytics REST routes, mounted at /api/v1/analytics/."""
from django.urls import path

from . import api_views

app_name = "analytics"

urlpatterns = [
    path("", api_views.DashboardAPIView.as_view(), name="dashboard"),
    path("metrics/", api_views.MetricListAPIView.as_view(), name="metrics"),
    path("metrics/<str:metric>/", api_views.MetricSeriesAPIView.as_view(), name="series"),
]
