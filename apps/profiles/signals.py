"""Profiles' reactions to platform events."""
import logging

from django.contrib.auth import get_user_model

from apps.common.events import Event, subscribe

from .models import Profile
from .services import PhotoService, ProfileService

logger = logging.getLogger(__name__)


@subscribe(Event.USER_REGISTERED)
def bootstrap_profile(envelope):
    """Every new identity gets an empty profile and default preferences."""
    user_id = envelope.payload.get("user_id")
    user = get_user_model().objects.filter(id=user_id).first()
    if user:
        ProfileService.get_or_create(user)


@subscribe(Event.USER_DEACTIVATED)
@subscribe(Event.USER_BANNED)
def hide_profile(envelope):
    user_id = envelope.payload.get("user_id")
    if user_id:
        Profile.objects.filter(user_id=user_id).update(is_visible=False)


@subscribe(Event.USER_ACTIVATED)
def show_profile(envelope):
    user_id = envelope.payload.get("user_id")
    if user_id:
        Profile.objects.filter(user_id=user_id).update(is_visible=True)


@subscribe(Event.CONTENT_FLAGGED)
def handle_photo_verdict(envelope):
    """Moderation publishes its verdict; profiles applies it to the gallery."""
    payload = envelope.payload
    if payload.get("object_type") != "profile_photo":
        return
    PhotoService.apply_moderation(
        payload["object_id"],
        approved=payload.get("approved", False),
        note=payload.get("reason", ""),
    )
