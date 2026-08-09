"""Background jobs owned by the chat service."""
from celery import shared_task
from django.utils import timezone

from .models import Conversation, Message


@shared_task(name="apps.chat.tasks.purge_deleted_messages")
def purge_deleted_messages(days=30):
    """Hard-delete messages that were soft-deleted a month ago."""
    cutoff = timezone.now() - timezone.timedelta(days=days)
    qs = Message.all_objects.filter(is_deleted=True, deleted_at__lt=cutoff)
    count = qs.count()
    qs.delete(hard=True)
    return count


@shared_task(name="apps.chat.tasks.archive_stale_conversations")
def archive_stale_conversations(days=180):
    cutoff = timezone.now() - timezone.timedelta(days=days)
    return Conversation.objects.filter(
        is_active=True, last_message_at__lt=cutoff
    ).update(is_active=False, closed_at=timezone.now(), close_reason="inactive")


@shared_task(name="apps.chat.tasks.scan_message_for_abuse")
def scan_message_for_abuse(message_id):
    """Deferred moderation pass for messages that need a slower check."""
    from apps.common.registry import services

    message = Message.objects.filter(id=message_id).first()
    if not message:
        return False
    verdict = services.moderation.screen_text(message.body, str(message.sender_id))
    if verdict.get("flagged"):
        message.is_flagged = True
        message.moderation_note = verdict.get("reason", "")[:255]
        message.save(update_fields=["is_flagged", "moderation_note"])
    return verdict.get("flagged", False)
