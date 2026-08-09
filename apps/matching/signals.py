"""Matching cache invalidation, driven by events."""
from apps.common.events import Event, subscribe

from .services import MatchingService


@subscribe(Event.PROFILE_UPDATED)
@subscribe(Event.PREFERENCES_UPDATED)
@subscribe(Event.PHOTO_UPLOADED)
def invalidate_scores(envelope):
    """Any change to a profile makes every score involving it stale."""
    user_id = envelope.payload.get("user_id")
    if user_id:
        MatchingService.invalidate_for(user_id)


@subscribe(Event.USER_DELETED)
def purge_scores(envelope):
    user_id = envelope.payload.get("user_id")
    if user_id:
        MatchingService.invalidate_for(user_id)
