from django.urls import path

from . import views

app_name = "matches"

urlpatterns = [
    path("", views.MatchListView.as_view(), name="list"),
    path("<uuid:pk>/", views.MatchDetailView.as_view(), name="detail"),
    path("<uuid:pk>/unmatch/", views.UnmatchView.as_view(), name="unmatch"),
]
