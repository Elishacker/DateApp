"""Aggregated WebSocket routes.

Each real-time module owns its own ``routing.py``; this file only composes them,
so extracting ``chat`` into a standalone ASGI service means deleting one line.
"""
from apps.chat.routing import websocket_urlpatterns as chat_ws
from apps.notifications.routing import websocket_urlpatterns as notification_ws

websocket_urlpatterns = [*chat_ws, *notification_ws]
