from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("blocked/", views.BlockListView.as_view(), name="blocked"),
    path("support/", views.SupportView.as_view(), name="support"),
    path("queue/", views.ReportQueueView.as_view(), name="queue"),
    path("user/<uuid:user_id>/", views.ReportUserView.as_view(), name="report_user"),
    path("user/<uuid:user_id>/block/", views.BlockUserView.as_view(), name="block"),
    path("user/<uuid:user_id>/unblock/", views.UnblockView.as_view(), name="unblock"),
    path("<uuid:report_id>/resolve/", views.ResolveReportView.as_view(), name="resolve"),
]
