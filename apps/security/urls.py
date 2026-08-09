from django.urls import path

from . import views

app_name = "security"

urlpatterns = [
    path("", views.MySecurityView.as_view(), name="my_security"),
    path("dashboard/", views.SecurityDashboardView.as_view(), name="dashboard"),
]
