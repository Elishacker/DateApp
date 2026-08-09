"""Accounts REST routes, mounted by the api gateway at /api/v1/accounts/."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import api_views

router = DefaultRouter()
router.register("devices", api_views.DeviceViewSet, basename="device")

app_name = "accounts"

urlpatterns = [
    path("me/", api_views.MeView.as_view(), name="me"),
    path("settings/", api_views.AccountSettingsView.as_view(), name="settings"),
    path("deactivate/", api_views.DeactivateAccountView.as_view(), name="deactivate"),
    path("delete/", api_views.DeleteAccountView.as_view(), name="delete"),
    path("", include(router.urls)),
]
