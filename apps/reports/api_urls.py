"""Reports REST routes, mounted at /api/v1/reports/."""
from django.urls import path

from . import api_views

app_name = "reports"

urlpatterns = [
    path("", api_views.ReportAPIView.as_view(), name="report"),
    path("blocks/", api_views.BlockAPIView.as_view(), name="blocks"),
    path("support/", api_views.SupportTicketAPIView.as_view(), name="support"),
    path("queue/", api_views.ReportQueueAPIView.as_view(), name="queue"),
]
