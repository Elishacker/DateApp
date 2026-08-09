"""Chat business logic and WebSocket fan-out."""
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.common.events import Event, publish
from apps.common.exceptions import ModerationBlocked, NotFound, PermissionDenied, ValidationError
from apps.common.registry import services

from .models import Conversation, ConversationMember, Message, MessageReaction, MessageType

logger = logging.getLogger(__name__)


def conversation_group(conversation_id):
    return f"chat_{conversation_id}"


def user_group(user_id):
    return f"user_{user_id}"


class ConversationService:
    @staticmethod
    @transaction.atomic
    def get_or_create(match_id, participant_ids):
        conversation = Conversation.objects.filter(match_id=match_id).first()
        if conversation:
            return conversation

        # These two may already be talking without a match. A new match adopts
        # that thread rather than starting a second one beside it — otherwise
        # matching someone you were already chatting with would lose the history.
        if len(participant_ids) == 2:
            existing = ConversationService.between(*participant_ids)
            if existing and not existing.match_id:
                existing.match_id = match_id
                existing.is_active = True
                existing.save(update_fields=["match_id", "is_active", "updated_at"])
                return existing

        conversation = Conversation.objects.create(match_id=match_id)
        for user_id in participant_ids:
            ConversationMember.objects.get_or_create(conversation=conversation, user_id=user_id)

        publish(Event.CONVERSATION_STARTED, {
            "conversation_id": str(conversation.id),
            "match_id": str(match_id),
            "participants": [str(p) for p in participant_ids],
        })
        return conversation

    @staticmethod
    def between(user_a, user_b):
        """The one conversation these two share — match-born or direct."""
        return (
            Conversation.objects.filter(members__user_id=user_a)
            .filter(members__user_id=user_b)
            .distinct()
            .first()
        )

    @staticmethod
    def assert_can_chat(viewer_id, target_id):
        """Safety gate for opening a conversation.

        Deliberately says nothing about likes, super likes, matches or plans:
        messaging is a normal thing to do on Zynora, and the only reasons to
        refuse are safety ones. Sending is still metered by the plan's daily
        message limit, which ``MessageService.send`` enforces.
        """
        viewer_id, target_id = str(viewer_id), str(target_id)
        if viewer_id == target_id:
            raise ValidationError("You cannot message yourself.")
        if not services.accounts.is_active_member(target_id):
            raise NotFound("That member is no longer available.")
        if services.reports.is_blocked_between(viewer_id, target_id):
            raise PermissionDenied("You cannot message this person.")
        return True

    @staticmethod
    @transaction.atomic
    def open_with(viewer_id, target_id):
        """Hand back the conversation with someone, creating it if needed.

        This is the single entry point behind every "message" button.
        """
        ConversationService.assert_can_chat(viewer_id, target_id)

        conversation = ConversationService.between(viewer_id, target_id)
        if conversation:
            # Rejoin a thread the viewer previously left or archived.
            ConversationMember.objects.filter(
                conversation=conversation, user_id=viewer_id
            ).update(left_at=None, is_archived=False)
            return conversation

        conversation = Conversation.objects.create()
        for user_id in (viewer_id, target_id):
            ConversationMember.objects.get_or_create(conversation=conversation, user_id=user_id)

        publish(Event.CONVERSATION_STARTED, {
            "conversation_id": str(conversation.id),
            "match_id": None,
            "participants": [str(viewer_id), str(target_id)],
        }, actor_id=viewer_id)
        return conversation

    @staticmethod
    def get_for_user(conversation_id, user_id):
        conversation = Conversation.objects.filter(id=conversation_id).first()
        if not conversation:
            raise NotFound("Conversation not found.")
        if not ConversationMember.objects.filter(
            conversation=conversation, user_id=user_id, left_at__isnull=True
        ).exists():
            raise PermissionDenied("You are not part of this conversation.")
        return conversation

    @staticmethod
    def list_for_user(user_id, include_archived=False):
        qs = ConversationMember.objects.filter(user_id=user_id, left_at__isnull=True)
        if not include_archived:
            qs = qs.filter(is_archived=False)
        return (
            Conversation.objects.filter(
                id__in=qs.values_list("conversation_id", flat=True), is_active=True
            ).order_by("-last_message_at", "-created_at")
        )

    @staticmethod
    def rows_for_user(user_id, active_id=None):
        """Render-ready conversation rows: the inbox, the rail and the API.

        Everything the caller needs is resolved here — peer identity, preview,
        unread count — so no template or serializer has to compute anything.
        """
        user_id = str(user_id)
        conversations = list(ConversationService.list_for_user(user_id))

        member_map = {
            m.conversation_id: m
            for m in ConversationMember.objects.filter(
                user_id=user_id, conversation__in=conversations
            )
        }
        other_ids = {}
        for conversation in conversations:
            other = ConversationMember.objects.filter(
                conversation=conversation
            ).exclude(user_id=user_id).values_list("user_id", flat=True).first()
            if other:
                other_ids[conversation.id] = str(other)

        refs = services.accounts.get_user_refs(list(other_ids.values()))

        rows = []
        for conversation in conversations:
            other_id = other_ids.get(conversation.id)
            ref = refs.get(other_id) if other_id else None
            if not ref:
                continue
            member = member_map.get(conversation.id)
            conversation_id = str(conversation.id)
            rows.append({
                "conversation_id": conversation_id,
                "user": ref,
                "preview": conversation.last_message_preview or "Say hello",
                "last_message_at": conversation.last_message_at,
                "unread_count": member.unread_count if member else 0,
                "has_unread": bool(member and member.unread_count),
                "is_muted": bool(member and member.is_muted),
                "is_match": bool(conversation.match_id),
                "is_active_row": bool(active_id) and conversation_id == str(active_id),
            })
        return rows

    @staticmethod
    def member(conversation_id, user_id):
        return ConversationMember.objects.filter(
            conversation_id=conversation_id, user_id=user_id
        ).first()

    @staticmethod
    def mark_read(conversation_id, user_id):
        member = ConversationService.member(conversation_id, user_id)
        if not member:
            return 0

        updated = Message.objects.filter(
            conversation_id=conversation_id, is_read=False
        ).exclude(sender_id=user_id).update(is_read=True, read_at=timezone.now())

        member.unread_count = 0
        member.last_read_at = timezone.now()
        member.save(update_fields=["unread_count", "last_read_at"])

        if updated:
            ChatBroadcaster.read_receipt(conversation_id, user_id)
            publish(Event.MESSAGE_READ, {
                "conversation_id": str(conversation_id),
                "reader_id": str(user_id),
                "count": updated,
            }, actor_id=user_id)
        return updated

    @staticmethod
    def set_typing(conversation_id, user_id, is_typing=True):
        ConversationMember.objects.filter(
            conversation_id=conversation_id, user_id=user_id
        ).update(last_typed_at=timezone.now() if is_typing else None)
        ChatBroadcaster.typing(conversation_id, user_id, is_typing)

    @staticmethod
    def archive(conversation_id, user_id, archived=True):
        return ConversationMember.objects.filter(
            conversation_id=conversation_id, user_id=user_id
        ).update(is_archived=archived)

    @staticmethod
    def mute(conversation_id, user_id, muted=True):
        return ConversationMember.objects.filter(
            conversation_id=conversation_id, user_id=user_id
        ).update(is_muted=muted)

    @staticmethod
    def close(conversation_id, reason="unmatched"):
        return Conversation.objects.filter(id=conversation_id).update(
            is_active=False, closed_at=timezone.now(), close_reason=reason[:140]
        )

    @staticmethod
    def close_for_match(match_id, reason="unmatched"):
        return Conversation.objects.filter(match_id=match_id).update(
            is_active=False, closed_at=timezone.now(), close_reason=reason[:140]
        )


class MessageService:
    @staticmethod
    @transaction.atomic
    def send(sender, conversation_id, *, body="", kind=MessageType.TEXT,
             attachment=None, voice_note=None, video=None, document=None,
             gif_url="", reply_to_id=None, voice_duration=None):
        conversation = ConversationService.get_for_user(conversation_id, sender.id)
        if not conversation.is_active:
            raise ValidationError("This conversation is closed.")

        member = ConversationService.member(conversation_id, sender.id)
        other = conversation.members.exclude(user_id=sender.id).first()
        if not other:
            raise ValidationError("There is nobody to message.")

        if services.reports.is_blocked_between(str(sender.id), str(other.user_id)):
            raise PermissionDenied("You cannot message this person.")

        if kind == MessageType.TEXT:
            body = (body or "").strip()
            if not body:
                raise ValidationError("Write something first.")
            verdict = services.moderation.screen_text(body, str(sender.id))
            if verdict.get("blocked"):
                raise ModerationBlocked(
                    verdict.get("reason", "That message was blocked by our safety filters.")
                )
            body = verdict.get("clean_text", body)

        if not services.subscriptions.can_send_message(str(sender.id), str(conversation_id)):
            from apps.common.exceptions import QuotaExceeded

            raise QuotaExceeded("You've reached your daily message limit. Upgrade to keep chatting.")

        message = Message.objects.create(
            conversation=conversation, sender=sender, kind=kind, body=body,
            attachment=attachment, voice_note=voice_note, video=video,
            document=document, document_name=document.name[:255] if document else "",
            gif_url=gif_url, voice_duration_seconds=voice_duration, reply_to_id=reply_to_id,
        )

        # Denormalised conversation state, so the list view needs no joins.
        conversation.last_message_at = message.created_at
        conversation.last_message_preview = MessageService.preview_for(message)
        conversation.message_count = F("message_count") + 1
        conversation.save(update_fields=["last_message_at", "last_message_preview",
                                         "message_count", "updated_at"])

        ConversationMember.objects.filter(conversation=conversation).exclude(
            user_id=sender.id
        ).update(unread_count=F("unread_count") + 1)

        payload = MessageService.serialize(message)
        ChatBroadcaster.new_message(conversation_id, payload)
        ChatBroadcaster.conversation_bump(str(other.user_id), conversation_id, payload)

        publish(Event.MESSAGE_SENT, {
            "message_id": str(message.id),
            "conversation_id": str(conversation.id),
            "match_id": str(conversation.match_id) if conversation.match_id else None,
            "sender_id": str(sender.id),
            "receiver_id": str(other.user_id),
            "kind": kind,
            "preview": conversation.last_message_preview,
            "is_muted": other.is_muted,
        }, actor_id=sender.id)

        if member:
            member.last_read_at = timezone.now()
            member.save(update_fields=["last_read_at"])
        return message

    @staticmethod
    def history(conversation_id, user_id, limit=50, before=None):
        ConversationService.get_for_user(conversation_id, user_id)
        qs = Message.objects.filter(conversation_id=conversation_id)
        if before:
            qs = qs.filter(created_at__lt=before)
        messages = list(qs.select_related("sender", "reply_to")[:limit])
        messages.reverse()  # oldest first for rendering
        return [MessageService.serialize(m, viewer_id=user_id) for m in messages]

    @staticmethod
    def delete(user, message_id):
        message = Message.objects.filter(id=message_id, sender=user).first()
        if not message:
            raise NotFound("Message not found.")
        message.delete()  # soft delete
        ChatBroadcaster.message_deleted(str(message.conversation_id), str(message.id))
        return True

    @staticmethod
    def react(user, message_id, emoji):
        message = Message.objects.filter(id=message_id).first()
        if not message:
            raise NotFound("Message not found.")
        ConversationService.get_for_user(message.conversation_id, user.id)

        reaction, created = MessageReaction.objects.get_or_create(
            message=message, user=user, emoji=emoji[:8]
        )
        if not created:
            reaction.delete()
        ChatBroadcaster.reaction(
            str(message.conversation_id), str(message.id), emoji, str(user.id), created
        )
        return created

    # ---- presentation -------------------------------------------------------
    @staticmethod
    def preview_for(message):
        """One-line summary shown in the conversation list."""
        if message.kind == MessageType.TEXT:
            return message.body[:140]
        return {
            MessageType.IMAGE: "Photo",
            MessageType.VOICE: "Voice note",
            MessageType.VIDEO: "Video",
            MessageType.DOCUMENT: message.document_name or "Document",
            MessageType.GIF: "GIF",
            MessageType.SYSTEM: message.body[:140],
        }.get(message.kind, "Message")

    @staticmethod
    def serialize(message, viewer_id=None):
        """Wire/render shape. Everything the UI needs, already formatted."""
        return {
            "id": str(message.id),
            "conversation_id": str(message.conversation_id),
            "sender_id": str(message.sender_id),
            "is_mine": str(message.sender_id) == str(viewer_id) if viewer_id else False,
            "kind": message.kind,
            "body": message.body,
            "attachment_url": message.attachment_url,
            "voice_url": message.voice_url,
            "voice_duration_seconds": message.voice_duration_seconds,
            "video_url": message.video_url,
            "document_url": message.document_url,
            "document_name": message.document_name,
            "gif_url": message.gif_url,
            "reply_to_id": str(message.reply_to_id) if message.reply_to_id else None,
            "reply_to_body": message.reply_to.body[:80] if message.reply_to else "",
            "is_read": message.is_read,
            "is_edited": message.is_edited,
            "is_deleted": message.is_deleted,
            "created_at": message.created_at.isoformat(),
            "time_label": timezone.localtime(message.created_at).strftime("%H:%M"),
        }


class ChatBroadcaster:
    """All WebSocket fan-out in one place.

    Wrapped so a broken channel layer can never fail a database transaction.
    """

    @staticmethod
    def _send(group, payload):
        layer = get_channel_layer()
        if not layer:
            return
        try:
            async_to_sync(layer.group_send)(group, payload)
        except Exception:  # noqa: BLE001
            logger.exception("channel fan-out failed for %s", group)

    @staticmethod
    def new_message(conversation_id, message_payload):
        ChatBroadcaster._send(conversation_group(conversation_id),
                              {"type": "chat.message", "message": message_payload})

    @staticmethod
    def message_deleted(conversation_id, message_id):
        ChatBroadcaster._send(conversation_group(conversation_id),
                              {"type": "chat.deleted", "message_id": message_id})

    @staticmethod
    def typing(conversation_id, user_id, is_typing):
        ChatBroadcaster._send(conversation_group(conversation_id),
                              {"type": "chat.typing", "user_id": str(user_id),
                               "is_typing": is_typing})

    @staticmethod
    def read_receipt(conversation_id, reader_id):
        ChatBroadcaster._send(conversation_group(conversation_id),
                              {"type": "chat.read", "reader_id": str(reader_id)})

    @staticmethod
    def reaction(conversation_id, message_id, emoji, user_id, added):
        ChatBroadcaster._send(conversation_group(conversation_id),
                              {"type": "chat.reaction", "message_id": message_id,
                               "emoji": emoji, "user_id": user_id, "added": added})

    @staticmethod
    def presence(user_id, is_online):
        ChatBroadcaster._send(user_group(user_id),
                              {"type": "chat.presence", "user_id": str(user_id),
                               "is_online": is_online})

    @staticmethod
    def conversation_bump(user_id, conversation_id, message_payload):
        """Notifies the recipient's conversation list even if that chat is closed."""
        ChatBroadcaster._send(user_group(user_id),
                              {"type": "chat.bump",
                               "conversation_id": str(conversation_id),
                               "message": message_payload})
