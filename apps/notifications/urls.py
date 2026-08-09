from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.InboxView.as_view(), name="inbox"),
    path("read/", views.MarkReadView.as_view(), name="mark_all_read"),
    path("read/<uuid:pk>/", views.MarkReadView.as_view(), name="mark_read"),
    path("clear/", views.ClearInboxView.as_view(), name="clear"),
    path("<uuid:pk>/delete/", views.DeleteNotificationView.as_view(), name="delete"),
    path("count/", views.UnreadCountView.as_view(), name="count"),
]
