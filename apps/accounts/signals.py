"""Accounts' subscriptions to the platform event bus.

This is how accounts keeps its read model current without ever importing
``apps.profiles`` or ``apps.verification``.
"""
import logging

from apps.common.events import Event, subscribe

from .services import AccountService

logger = logging.getLogger(__name__)


@subscribe(Event.PROFILE_UPDATED)
@subscribe(Event.PHOTO_UPLOADED)
def project_avatar(envelope):
    """Mirror the primary photo URL so ``get_user_ref`` needs no join."""
    payload = envelope.payload
    if "avatar_url" in payload and payload.get("user_id"):
        AccountService.update_avatar_projection(payload["user_id"], payload["avatar_url"])


@subscribe(Event.EMAIL_VERIFIED)
def flag_email_verified(envelope):
    user_id = envelope.payload.get("user_id")
    if user_id:
        AccountService.set_verification_flag(user_id, "is_email_verified", True)
        AccountService.activate(user_id)


@subscribe(Event.VERIFICATION_APPROVED)
def flag_verification(envelope):
    payload = envelope.payload
    mapping = {
        "phone": "is_phone_verified",
        "photo": "is_photo_verified",
        "selfie": "is_photo_verified",
        "identity": "is_identity_verified",
        "government_id": "is_identity_verified",
    }
    flag = mapping.get(payload.get("kind"))
    if flag and payload.get("user_id"):
        AccountService.set_verification_flag(payload["user_id"], flag, True)


@subscribe(Event.ONBOARDING_COMPLETED)
def close_onboarding(envelope):
    from .models import User

    user_id = envelope.payload.get("user_id")
    if user_id:
        User.objects.filter(id=user_id).update(has_completed_onboarding=True)
