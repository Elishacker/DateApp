"""Authentication's reactions to platform events."""
import logging

from django.utils import timezone

from apps.common.events import Event, subscribe

from .models import ActiveSession

logger = logging.getLogger("zynora.security")


@subscribe(Event.USER_BANNED)
def kill_sessions_on_ban(envelope):
    """A banned account must lose every live session immediately."""
    user_id = envelope.payload.get("user_id")
    if user_id:
        revoked = ActiveSession.objects.filter(
            user_id=user_id, revoked_at__isnull=True
        ).update(revoked_at=timezone.now())
        logger.warning("revoked %s session(s) for banned user %s", revoked, user_id)


@subscribe(Event.SECURITY_ANOMALY)
def force_reauth_on_anomaly(envelope):
    """High-severity anomalies invalidate every session except the current one."""
    payload = envelope.payload
    if payload.get("severity") != "high" or not payload.get("user_id"):
        return
    ActiveSession.objects.filter(
        user_id=payload["user_id"], revoked_at__isnull=True
    ).exclude(device_fingerprint=payload.get("device_fingerprint", "")).update(
        revoked_at=timezone.now()
    )
