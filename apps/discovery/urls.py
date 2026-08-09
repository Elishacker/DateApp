from django.urls import path

from . import views

app_name = "discovery"

urlpatterns = [
    path("", views.FeedView.as_view(), name="feed"),
    path("search/", views.SearchView.as_view(), name="search"),
    path("admirers/", views.AdmirersView.as_view(), name="admirers"),
    path("swipe/", views.SwipeView.as_view(), name="swipe"),
    path("rewind/", views.RewindView.as_view(), name="rewind"),
    path("refresh/", views.FeedRefreshView.as_view(), name="refresh"),
]
