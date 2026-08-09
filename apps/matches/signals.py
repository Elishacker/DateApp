"""Matches' reactions to platform events."""
import logging

from apps.common.events import Event, subscribe

from .services import MatchService

logger = logging.getLogger(__name__)


@subscribe(Event.USER_BLOCKED)
def end_match_on_block(envelope):
    payload = envelope.payload
    if payload.get("blocker_id") and payload.get("blocked_id"):
        MatchService.end_all_for_pair(
            payload["blocker_id"], payload["blocked_id"], reason="blocked"
        )


@subscribe(Event.USER_BANNED)
@subscribe(Event.USER_DEACTIVATED)
def end_matches_on_exit(envelope):
    user_id = envelope.payload.get("user_id")
    if user_id:
        count = MatchService.end_all_for_user(user_id, reason="account unavailable")
        logger.info("ended %d match(es) for %s", count, user_id)


@subscribe(Event.MESSAGE_SENT)
def bump_match_activity(envelope):
    """Keeps the match list sorted by real conversation activity."""
    match_id = envelope.payload.get("match_id")
    if match_id:
        MatchService.touch(match_id, message_count_delta=1)
