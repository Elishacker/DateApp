from django.urls import path

from . import views

app_name = "likes"

urlpatterns = [
    path("", views.SentLikesView.as_view(), name="sent"),
    path("quota/", views.QuotaView.as_view(), name="quota"),
]
