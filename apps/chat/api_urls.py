"""Chat REST routes, mounted at /api/v1/chat/."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import api_views

router = DefaultRouter()
router.register("conversations", api_views.ConversationViewSet, basename="conversation")

app_name = "chat"

urlpatterns = [
    path("unread/", api_views.UnreadCountView.as_view(), name="unread"),
    path("messages/<uuid:message_id>/", api_views.MessageActionView.as_view(), name="message"),
    path("", include(router.urls)),
]
