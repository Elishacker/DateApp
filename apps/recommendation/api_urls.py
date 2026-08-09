"""Recommendation REST routes, mounted at /api/v1/recommendations/."""
from django.urls import path

from . import api_views

app_name = "recommendation"

urlpatterns = [
    path("", api_views.AllRecommendationsAPIView.as_view(), name="all"),
    path("<str:set_name>/", api_views.RecommendationSetAPIView.as_view(), name="set"),
]
