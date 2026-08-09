"""Moderation's reactions to platform events."""
from django.db.models import F

from apps.common.events import Event, subscribe

from .models import TrustScore
from .services import TrustService


@subscribe(Event.USER_REPORTED)
def count_report(envelope):
    reported_id = envelope.payload.get("reported_id")
    if reported_id:
        TrustService.get(reported_id)  # ensure the row exists
        TrustScore.objects.filter(user_id=reported_id).update(
            reports_received=F("reports_received") + 1
        )


@subscribe(Event.ONBOARDING_COMPLETED)
def reward_completion(envelope):
    """A finished profile is a small positive trust signal."""
    user_id = envelope.payload.get("user_id")
    if user_id:
        TrustService.reward(user_id, points=5)


@subscribe(Event.VERIFICATION_APPROVED)
def reward_verification(envelope):
    user_id = envelope.payload.get("user_id")
    if user_id:
        TrustService.reward(user_id, points=10)
