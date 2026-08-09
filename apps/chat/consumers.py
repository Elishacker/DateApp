"""WebSocket consumers for real-time chat.

Two sockets per member:
  * ``/ws/chat/<conversation_id>/`` — one open conversation;
  * ``/ws/presence/`` — conversation-list bumps and online presence.

Authorisation is re-checked on connect; a socket is never trusted because it was
opened earlier.
"""
import json
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

logger = logging.getLogger(__name__)


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope.get("user")
        self.conversation_id = self.scope["url_route"]["kwargs"]["conversation_id"]
        if not self.user or not self.user.is_authenticated:
            await self.close(code=4401)
            return

        if not await self._is_member():
            await self.close(code=4403)
            return

        self.group = f"chat_{self.conversation_id}"
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()

        await self._set_online(True)
        history = await self._history()
        await self.send(json.dumps({"type": "history", "messages": history}))

    async def disconnect(self, code):
        if hasattr(self, "group"):
            await self.channel_layer.group_discard(self.group, self.channel_name)
        if getattr(self, "user", None) and self.user.is_authenticated:
            await self._set_typing(False)

    async def receive(self, text_data=None, bytes_data=None):
        try:
            data = json.loads(text_data or "{}")
        except json.JSONDecodeError:
            return await self._error("Malformed payload.")

        action = data.get("action")
        if action == "send":
            await self._handle_send(data)
        elif action == "typing":
            await self._set_typing(bool(data.get("is_typing", True)))
        elif action == "read":
            await self._mark_read()
        elif action == "react":
            await self._handle_react(data)
        elif action == "load_more":
            messages = await self._history(before=data.get("before"))
            await self.send(json.dumps({"type": "history_page", "messages": messages}))

    # ---- actions ------------------------------------------------------------
    async def _handle_send(self, data):
        body = (data.get("body") or "").strip()
        if not body:
            return await self._error("Write something first.")
        try:
            await self._create_message(body, data.get("reply_to"))
        except Exception as exc:  # noqa: BLE001 - surfaced to the client
            await self._error(getattr(exc, "message", str(exc)))

    async def _handle_react(self, data):
        message_id, emoji = data.get("message_id"), data.get("emoji")
        if message_id and emoji:
            await self._react(message_id, emoji)

    async def _error(self, message):
        await self.send(json.dumps({"type": "error", "message": message}))

    # ---- group event handlers ----------------------------------------------
    async def chat_message(self, event):
        await self.send(json.dumps({"type": "message", "message": event["message"]}))

    async def chat_deleted(self, event):
        await self.send(json.dumps({"type": "deleted", "message_id": event["message_id"]}))

    async def chat_typing(self, event):
        if str(event["user_id"]) != str(self.user.id):
            await self.send(json.dumps({"type": "typing", "user_id": event["user_id"],
                                        "is_typing": event["is_typing"]}))

    async def chat_read(self, event):
        if str(event["reader_id"]) != str(self.user.id):
            await self.send(json.dumps({"type": "read", "reader_id": event["reader_id"]}))

    async def chat_reaction(self, event):
        await self.send(json.dumps({
            "type": "reaction", "message_id": event["message_id"],
            "emoji": event["emoji"], "user_id": event["user_id"], "added": event["added"],
        }))

    # ---- database bridges ---------------------------------------------------
    @database_sync_to_async
    def _is_member(self):
        from .models import ConversationMember

        return ConversationMember.objects.filter(
            conversation_id=self.conversation_id, user=self.user, left_at__isnull=True
        ).exists()

    @database_sync_to_async
    def _history(self, before=None):
        from .services import MessageService

        return MessageService.history(self.conversation_id, self.user.id, before=before)

    @database_sync_to_async
    def _create_message(self, body, reply_to=None):
        from .services import MessageService

        MessageService.send(self.user, self.conversation_id, body=body, reply_to_id=reply_to)

    @database_sync_to_async
    def _mark_read(self):
        from .services import ConversationService

        return ConversationService.mark_read(self.conversation_id, self.user.id)

    @database_sync_to_async
    def _set_typing(self, is_typing):
        from .services import ConversationService

        ConversationService.set_typing(self.conversation_id, self.user.id, is_typing)

    @database_sync_to_async
    def _react(self, message_id, emoji):
        from .services import MessageService

        MessageService.react(self.user, message_id, emoji)

    @database_sync_to_async
    def _set_online(self, online):
        from apps.common.registry import services

        services.accounts.set_online(str(self.user.id), online)


class PresenceConsumer(AsyncWebsocketConsumer):
    """Per-user socket: conversation-list bumps, presence and match alerts."""

    async def connect(self):
        self.user = self.scope.get("user")
        if not self.user or not self.user.is_authenticated:
            await self.close(code=4401)
            return

        self.group = f"user_{self.user.id}"
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()
        await self._set_online(True)
        await self.send(json.dumps({"type": "connected"}))

    async def disconnect(self, code):
        if hasattr(self, "group"):
            await self.channel_layer.group_discard(self.group, self.channel_name)
        if getattr(self, "user", None) and self.user.is_authenticated:
            await self._set_online(False)

    async def receive(self, text_data=None, bytes_data=None):
        try:
            data = json.loads(text_data or "{}")
        except json.JSONDecodeError:
            return
        if data.get("action") == "ping":
            await self.send(json.dumps({"type": "pong"}))

    async def chat_bump(self, event):
        await self.send(json.dumps({
            "type": "conversation_bump",
            "conversation_id": event["conversation_id"],
            "message": event["message"],
        }))

    async def chat_presence(self, event):
        await self.send(json.dumps({
            "type": "presence", "user_id": event["user_id"], "is_online": event["is_online"],
        }))

    async def match_created(self, event):
        await self.send(json.dumps({"type": "match", "match": event["match"]}))

    @database_sync_to_async
    def _set_online(self, online):
        from apps.common.registry import services

        services.accounts.set_online(str(self.user.id), online)
