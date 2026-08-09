from django.urls import path

from . import views

app_name = "chat"

urlpatterns = [
    path("", views.InboxView.as_view(), name="inbox"),
    path("with/<uuid:user_id>/", views.StartConversationView.as_view(), name="with"),
    path("<uuid:pk>/", views.ConversationView.as_view(), name="conversation"),
    path("<uuid:pk>/send/", views.SendMessageView.as_view(), name="send"),
    path("<uuid:pk>/mute/", views.MuteConversationView.as_view(), name="mute"),
    path("<uuid:pk>/archive/", views.ArchiveConversationView.as_view(), name="archive"),
    path("message/<uuid:message_id>/delete/", views.DeleteMessageView.as_view(), name="delete"),
]
