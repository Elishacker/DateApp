"""Matching REST routes, mounted at /api/v1/matching/."""
from django.urls import path

from . import api_views

app_name = "matching"

urlpatterns = [
    path("top/", api_views.TopScoresAPIView.as_view(), name="top"),
    path("score/<uuid:user_id>/", api_views.ScorePairAPIView.as_view(), name="score"),
    path("explain/<uuid:user_id>/", api_views.ExplainPairAPIView.as_view(), name="explain"),
]
