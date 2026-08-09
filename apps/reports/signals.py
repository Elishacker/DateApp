"""Reports' reactions to platform events."""
from django.db.models import Q

from apps.common.events import Event, subscribe

from .models import Block
from .services import BlockService


@subscribe(Event.USER_DELETED)
def purge_blocks(envelope):
    user_id = envelope.payload.get("user_id")
    if user_id and not envelope.payload.get("scheduled", False):
        Block.objects.filter(Q(blocker_id=user_id) | Q(blocked_id=user_id)).delete()


@subscribe(Event.USER_BLOCKED)
def warm_block_cache(envelope):
    """Refresh the cached verdict so the very next feed render is correct."""
    payload = envelope.payload
    if payload.get("blocker_id") and payload.get("blocked_id"):
        BlockService._invalidate(payload["blocker_id"], payload["blocked_id"])
        BlockService.is_blocked_between(payload["blocker_id"], payload["blocked_id"])
