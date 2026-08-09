"""Matches REST routes, mounted at /api/v1/matches/."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import api_views

router = DefaultRouter()
router.register("", api_views.MatchViewSet, basename="match")

app_name = "matches"

urlpatterns = [
    path("counts/", api_views.MatchCountView.as_view(), name="counts"),
    path("", include(router.urls)),
]
