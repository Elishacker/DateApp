from django.urls import path

from . import views

app_name = "matching"

urlpatterns = [
    path("explain/<uuid:user_id>/", views.ExplainView.as_view(), name="explain"),
]
