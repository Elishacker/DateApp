"""Public contract of the chat service."""
from apps.common.interface import ModuleInterface

from .models import Conversation, ConversationMember, Message
from .services import ChatBroadcaster, ConversationService, MessageService


class ChatInterface(ModuleInterface):
    name = "chat"
    depends_on = ("accounts", "matches", "moderation", "reports", "subscriptions")

    def get_or_create_conversation(self, match_id, participant_ids):
        conversation = ConversationService.get_or_create(match_id, participant_ids)
        return str(conversation.id)

    def open_conversation_with(self, viewer_id, target_id):
        """Conversation id for these two, created on demand. Safety-checked."""
        conversation = ConversationService.open_with(viewer_id, target_id)
        return str(conversation.id)

    def get_conversation_id_between(self, user_a, user_b):
        conversation = ConversationService.between(user_a, user_b)
        return str(conversation.id) if conversation else None

    def get_conversation_id_for_match(self, match_id):
        conversation = Conversation.objects.filter(match_id=match_id).only("id").first()
        return str(conversation.id) if conversation else None

    def get_conversation_previews(self, user_id, other_user_ids):
        """Bulk preview lookup keyed by the *other* participant's id.

        Used by the match list so it can render last-message text and unread
        badges without the matches service knowing anything about messages.
        """
        memberships = ConversationMember.objects.filter(
            user_id=user_id, left_at__isnull=True
        ).select_related("conversation")

        by_other = {}
        for membership in memberships:
            other = ConversationMember.objects.filter(
                conversation_id=membership.conversation_id
            ).exclude(user_id=user_id).values_list("user_id", flat=True).first()
            if not other or str(other) not in {str(o) for o in other_user_ids}:
                continue
            conversation = membership.conversation
            by_other[str(other)] = {
                "conversation_id": str(conversation.id),
                "body": conversation.last_message_preview,
                "created_at": (
                    conversation.last_message_at.isoformat()
                    if conversation.last_message_at else None
                ),
                "unread_count": membership.unread_count,
                "message_count": conversation.message_count,
            }
        return by_other

    def count_unread_conversations(self, user_id):
        return ConversationMember.objects.filter(
            user_id=user_id, unread_count__gt=0, is_archived=False, left_at__isnull=True
        ).count()

    def count_unread_messages(self, user_id):
        from django.db.models import Sum

        total = ConversationMember.objects.filter(
            user_id=user_id, left_at__isnull=True
        ).aggregate(total=Sum("unread_count"))["total"]
        return total or 0

    def close_conversation_for_match(self, match_id, reason="unmatched"):
        return ConversationService.close_for_match(match_id, reason)

    def message_count_between(self, user_a, user_b):
        conversation = Conversation.objects.filter(
            members__user_id=user_a
        ).filter(members__user_id=user_b).first()
        return conversation.message_count if conversation else 0

    def flag_message(self, message_id, note=""):
        """Called by moderation when a message trips a filter after the fact."""
        return Message.objects.filter(id=message_id).update(
            is_flagged=True, moderation_note=note[:255]
        )

    def get_message(self, message_id):
        message = Message.objects.filter(id=message_id).first()
        return MessageService.serialize(message) if message else None

    def push_to_user(self, user_id, event_type, payload):
        """Generic per-user socket push, used by notifications."""
        ChatBroadcaster._send(f"user_{user_id}", {"type": event_type, **payload})
        return True

    def daily_stats(self, since=None):
        qs = Message.objects.all()
        if since:
            qs = qs.filter(created_at__gte=since)
        return {
            "messages": qs.count(),
            "conversations_active": Conversation.objects.filter(is_active=True).count(),
            "flagged": qs.filter(is_flagged=True).count(),
        }


service = ChatInterface()
