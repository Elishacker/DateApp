"""Discovery cache invalidation, driven entirely by events.

Discovery stores nothing, so its only reaction to change is dropping stale
feeds. It never needs to know which module raised the event.
"""
from apps.common.events import Event, subscribe

from .services import DiscoveryService


@subscribe(Event.PREFERENCES_UPDATED)
@subscribe(Event.PROFILE_UPDATED)
def drop_own_feed(envelope):
    user_id = envelope.payload.get("user_id")
    if user_id:
        DiscoveryService.invalidate(user_id)


@subscribe(Event.LIKE_SENT)
@subscribe(Event.SUPER_LIKE_SENT)
@subscribe(Event.PASS_SENT)
def drop_sender_feed(envelope):
    sender_id = envelope.payload.get("sender_id")
    if sender_id:
        DiscoveryService.invalidate(sender_id)


@subscribe(Event.MATCH_CREATED)
def drop_both_feeds(envelope):
    for key in ("user_a", "user_b"):
        if envelope.payload.get(key):
            DiscoveryService.invalidate(envelope.payload[key])


@subscribe(Event.USER_BLOCKED)
def drop_blocker_feed(envelope):
    for key in ("blocker_id", "blocked_id"):
        if envelope.payload.get(key):
            DiscoveryService.invalidate(envelope.payload[key])
