"""WebSocket routes owned by the chat service."""
from django.urls import re_path

from . import consumers

websocket_urlpatterns = [
    re_path(
        r"^ws/chat/(?P<conversation_id>[0-9a-f-]{36})/$",
        consumers.ChatConsumer.as_asgi(),
    ),
    re_path(r"^ws/presence/$", consumers.PresenceConsumer.as_asgi()),
]
