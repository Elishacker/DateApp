"""Chat's reactions to platform events."""
import logging

from apps.common.events import Event, subscribe

from .services import ConversationService

logger = logging.getLogger(__name__)


@subscribe(Event.MATCH_CREATED)
def open_conversation(envelope):
    """A new match immediately gets an (empty) conversation to write into."""
    payload = envelope.payload
    if payload.get("match_id") and payload.get("user_a") and payload.get("user_b"):
        ConversationService.get_or_create(
            payload["match_id"], [payload["user_a"], payload["user_b"]]
        )


@subscribe(Event.MATCH_ENDED)
def close_conversation(envelope):
    match_id = envelope.payload.get("match_id")
    if match_id:
        ConversationService.close_for_match(match_id, envelope.payload.get("reason", "unmatched"))


@subscribe(Event.USER_BANNED)
@subscribe(Event.USER_DELETED)
def close_all_conversations(envelope):
    from .models import Conversation, ConversationMember

    user_id = envelope.payload.get("user_id")
    if not user_id:
        return
    conversation_ids = ConversationMember.objects.filter(
        user_id=user_id
    ).values_list("conversation_id", flat=True)
    count = Conversation.objects.filter(id__in=list(conversation_ids)).update(is_active=False)
    logger.info("closed %d conversation(s) for %s", count, user_id)
