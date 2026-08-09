"""Chat REST endpoints (mobile client and WebSocket fallback)."""
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.viewsets import ViewSet

from apps.common.mixins import ServiceResponseMixin
from apps.common.permissions import IsOnboarded
from apps.common.registry import services

from .serializers import ReactionSerializer, SendMessageSerializer
from .services import ConversationService, MessageService


class ConversationViewSet(ServiceResponseMixin, ViewSet):
    permission_classes = [IsAuthenticated, IsOnboarded]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def list(self, request):
        rows = ConversationService.rows_for_user(str(request.user.id))
        return self.ok({"count": len(rows), "conversations": rows})

    def retrieve(self, request, pk=None):
        user_id = str(request.user.id)
        conversation = ConversationService.get_for_user(pk, user_id)
        other = conversation.members.exclude(user_id=user_id).first()
        ConversationService.mark_read(pk, user_id)
        return self.ok({
            "conversation_id": str(conversation.id),
            "person": services.accounts.get_user_ref(str(other.user_id)) if other else None,
            "is_active": conversation.is_active,
            "messages": MessageService.history(pk, user_id, limit=50),
        })

    @action(detail=True, methods=["get"])
    def messages(self, request, pk=None):
        before = request.query_params.get("before")
        limit = min(int(request.query_params.get("limit", 50)), 100)
        return self.ok({
            "messages": MessageService.history(pk, str(request.user.id),
                                               limit=limit, before=before),
        })

    @action(detail=True, methods=["post"])
    def send(self, request, pk=None):
        serializer = SendMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        message = MessageService.send(
            request.user, pk,
            body=data.get("body", ""), kind=data.get("kind"),
            attachment=data.get("attachment"), voice_note=data.get("voice_note"),
            video=data.get("video"), document=data.get("document"),
            voice_duration=data.get("voice_duration_seconds"),
            gif_url=data.get("gif_url", ""), reply_to_id=data.get("reply_to"),
        )
        return self.ok(
            MessageService.serialize(message, viewer_id=request.user.id),
            message="Sent.", status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        count = ConversationService.mark_read(pk, str(request.user.id))
        return self.ok({"marked_read": count})

    @action(detail=True, methods=["post"])
    def typing(self, request, pk=None):
        ConversationService.set_typing(
            pk, str(request.user.id), request.data.get("is_typing", True)
        )
        return self.ok()

    @action(detail=True, methods=["post"])
    def mute(self, request, pk=None):
        muted = bool(request.data.get("muted", True))
        ConversationService.mute(pk, str(request.user.id), muted)
        return self.ok({"muted": muted})

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        ConversationService.archive(pk, str(request.user.id), True)
        return self.ok(message="Archived.")


class MessageActionView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, message_id):
        MessageService.delete(request.user, message_id)
        return self.ok(message="Message deleted.")

    def post(self, request, message_id):
        serializer = ReactionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        added = MessageService.react(request.user, message_id, serializer.validated_data["emoji"])
        return self.ok({"added": added})


class UnreadCountView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_id = str(request.user.id)
        return self.ok({
            "conversations": services.chat.count_unread_conversations(user_id),
            "messages": services.chat.count_unread_messages(user_id),
        })
