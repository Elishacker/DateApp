"""Security's reactions to platform events."""
import logging

from apps.common.events import Event, subscribe

from .models import SecurityEvent
from .services import AnomalyService, ReputationService

logger = logging.getLogger("zynora.security")


@subscribe(Event.LOGIN_SUCCEEDED)
def score_login(envelope):
    """Every successful login is scored for anomalies after the fact."""
    payload = envelope.payload
    AnomalyService.evaluate_login(
        payload["user_id"],
        ip=payload.get("ip"),
        device_fingerprint=payload.get("device_fingerprint", ""),
        device_is_new=payload.get("device_is_new", False),
    )


@subscribe(Event.LOGIN_FAILED)
def penalise_failed_login(envelope):
    ip = envelope.payload.get("ip")
    if ip:
        ReputationService.penalise(ip, 3, "failed login")


@subscribe(Event.PASSWORD_CHANGED)
def note_password_change(envelope):
    payload = envelope.payload
    AnomalyService.record(
        SecurityEvent.Kind.NEW_DEVICE if payload.get("via") == "reset"
        else SecurityEvent.Kind.NEW_LOCATION,
        user_id=payload.get("user_id"),
        severity="info",
        description=f"Password changed via {payload.get('via', 'settings')}.",
    )


@subscribe(Event.USER_BANNED)
def blacklist_ip_of_banned_user(envelope):
    """A banned account's last known IP earns a reputation hit."""
    from apps.common.registry import services

    user_id = envelope.payload.get("user_id")
    if not user_id:
        return
    for ip in services.authentication.known_login_ips(user_id, limit=5):
        if ip:
            ReputationService.penalise(ip, 20, f"associated with banned user {user_id}")
