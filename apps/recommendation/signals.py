"""Recommendation cache invalidation, driven by events."""
from apps.common.events import Event, subscribe

from .services import RecommendationService


@subscribe(Event.PREFERENCES_UPDATED)
@subscribe(Event.PROFILE_UPDATED)
def rebuild_on_change(envelope):
    user_id = envelope.payload.get("user_id")
    if user_id:
        RecommendationService.invalidate(user_id)


@subscribe(Event.LIKE_SENT)
@subscribe(Event.SUPER_LIKE_SENT)
@subscribe(Event.PASS_SENT)
def record_action(envelope):
    """A swipe on a recommended profile is the signal we tune against."""
    payload = envelope.payload
    if payload.get("sender_id") and payload.get("receiver_id"):
        RecommendationService.mark_acted(payload["sender_id"], payload["receiver_id"])
