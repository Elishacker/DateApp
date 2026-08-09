"""Likes' reactions to platform events."""
from django.db.models import Q

from apps.common.events import Event, subscribe

from .models import Like


@subscribe(Event.USER_DELETED)
def purge_likes(envelope):
    user_id = envelope.payload.get("user_id")
    if user_id and not envelope.payload.get("scheduled", False):
        Like.objects.filter(Q(sender_id=user_id) | Q(receiver_id=user_id)).delete()


@subscribe(Event.USER_BLOCKED)
def drop_likes_between(envelope):
    """A block removes any pending intent in either direction."""
    payload = envelope.payload
    blocker, blocked = payload.get("blocker_id"), payload.get("blocked_id")
    if blocker and blocked:
        Like.objects.filter(
            Q(sender_id=blocker, receiver_id=blocked)
            | Q(sender_id=blocked, receiver_id=blocker)
        ).delete()
