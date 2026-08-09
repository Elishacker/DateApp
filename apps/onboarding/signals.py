"""Onboarding's reactions to platform events."""
from apps.common.events import Event, subscribe

from .models import OnboardingProgress


@subscribe(Event.USER_REGISTERED)
def start_wizard(envelope):
    user_id = envelope.payload.get("user_id")
    if user_id:
        OnboardingProgress.objects.get_or_create(user_id=user_id)
