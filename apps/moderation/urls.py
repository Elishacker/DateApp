from django.urls import path

from . import views

app_name = "moderation"

urlpatterns = [
    path("", views.QueueView.as_view(), name="queue"),
    path("trust/", views.TrustListView.as_view(), name="trust"),
    path("case/<uuid:case_id>/decide/", views.DecideView.as_view(), name="decide"),
    path("shadow-ban/<uuid:user_id>/", views.ShadowBanView.as_view(), name="shadow_ban"),
]
