from django.urls import path

from . import views

app_name = "recommendation"

urlpatterns = [
    path("", views.RecommendationsView.as_view(), name="sets"),
    path("top-picks/", views.TopPicksView.as_view(), name="top_picks"),
]
