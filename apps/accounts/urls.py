from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("", views.AccountOverviewView.as_view(), name="overview"),
    path("details/", views.AccountDetailsView.as_view(), name="details"),
    path("settings/", views.AccountSettingsView.as_view(), name="settings"),
    path("devices/", views.DeviceListView.as_view(), name="devices"),
    path("devices/<uuid:pk>/revoke/", views.DeviceRevokeView.as_view(), name="device_revoke"),
    path("deactivate/", views.DeactivateView.as_view(), name="deactivate"),
]
