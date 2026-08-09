from django.urls import path

from . import views

app_name = "audit"

urlpatterns = [
    path("", views.MyActivityView.as_view(), name="my_activity"),
    path("trail/", views.AuditTrailView.as_view(), name="trail"),
]
