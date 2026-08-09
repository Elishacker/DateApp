"""Verification's reactions to platform events."""
from apps.common.events import Event, subscribe

from .models import VerificationKind, VerificationRequest, VerificationStatus
from .services import VerificationService


@subscribe(Event.EMAIL_VERIFIED)
def record_email_badge(envelope):
    user_id = envelope.payload.get("user_id")
    if user_id:
        VerificationService._mark_badge(user_id, VerificationKind.EMAIL)


@subscribe(Event.CONTENT_FLAGGED)
def apply_photo_verdict(envelope):
    """Moderation reviews verification photos; the verdict lands here."""
    payload = envelope.payload
    if payload.get("object_type") != "verification_photo":
        return

    request = VerificationRequest.objects.filter(
        id=payload["object_id"], status=VerificationStatus.PENDING
    ).first()
    if not request:
        return

    if payload.get("approved"):
        VerificationService.approve(request)
    else:
        VerificationService.reject(
            request, payload.get("reason", "The photo did not match the requested pose.")
        )
