"""WebSocket routes owned by the notifications service.

The live notification stream reuses the chat presence socket group
(``user_<id>``), so this module contributes no additional consumer today.
Keeping the file means adding one later requires no change to config/routing.py.
"""

websocket_urlpatterns = []
