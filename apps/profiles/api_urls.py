"""Profiles REST routes, mounted at /api/v1/profiles/."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import api_views

router = DefaultRouter()
router.register("photos", api_views.PhotoViewSet, basename="photo")

app_name = "profiles"

urlpatterns = [
    path("me/", api_views.MyProfileView.as_view(), name="me"),
    path("preferences/", api_views.PreferenceView.as_view(), name="preferences"),
    path("location/", api_views.LocationView.as_view(), name="location"),
    path("interests/", api_views.InterestListView.as_view(), name="interests"),
    path("viewers/", api_views.ProfileViewersView.as_view(), name="viewers"),
    path("<uuid:user_id>/", api_views.PublicProfileView.as_view(), name="public"),
    path("", include(router.urls)),
]
