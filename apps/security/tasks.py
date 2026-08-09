"""Background jobs owned by the security service."""
import logging

from celery import shared_task
from django.utils import timezone

from .models import IPReputation, RateLimitBreach, SecurityEvent

logger = logging.getLogger("zynora.security")


@shared_task(name="apps.security.tasks.purge_stale_devices")
def purge_stale_devices(days=180):
    """Delegates to accounts, which owns the device registry."""
    from apps.common.registry import services

    return services.accounts.prune_revoked_devices(days)


@shared_task(name="apps.security.tasks.unblock_expired_ips")
def unblock_expired_ips():
    return IPReputation.objects.filter(
        is_blocked=True, blocked_until__lt=timezone.now()
    ).update(is_blocked=False, blocked_until=None)


@shared_task(name="apps.security.tasks.decay_ip_reputation")
def decay_ip_reputation(points=5):
    """Slowly restore reputation so a one-off incident isn't permanent."""
    from django.db.models import F, Value
    from django.db.models.functions import Least

    cutoff = timezone.now() - timezone.timedelta(days=7)
    return IPReputation.objects.filter(
        last_seen_at__lt=cutoff, score__lt=100, is_blocked=False
    ).update(score=Least(F("score") + points, Value(100)))


@shared_task(name="apps.security.tasks.prune_security_data")
def prune_security_data(days=180):
    cutoff = timezone.now() - timezone.timedelta(days=days)
    events, _ = SecurityEvent.objects.filter(
        created_at__lt=cutoff, is_resolved=True
    ).delete()
    breaches, _ = RateLimitBreach.objects.filter(created_at__lt=cutoff).delete()
    return {"events": events, "breaches": breaches}


@shared_task(name="apps.security.tasks.detect_credential_stuffing")
def detect_credential_stuffing(threshold=20, window_minutes=15):
    """One IP failing against many distinct accounts is a stuffing pattern.

    The raw telemetry belongs to the authentication service, so we ask it for
    the aggregate rather than querying its ledger.
    """
    from apps.common.registry import services

    suspects = services.authentication.failed_attempts_by_ip(threshold, window_minutes)

    flagged = 0
    for row in suspects:
        ip, accounts = row["ip"], row["accounts"]
        record, _ = IPReputation.objects.get_or_create(ip_address=ip)
        record.penalise(60, f"credential stuffing: {accounts} accounts")
        SecurityEvent.objects.create(
            kind=SecurityEvent.Kind.CREDENTIAL_STUFFING,
            severity="critical",
            description=f"{accounts} distinct accounts targeted from {ip}.",
            risk_score=90, ip_address=ip,
            metadata={"accounts": accounts, "window_minutes": window_minutes},
        )
        logger.error("credential stuffing from %s (%d accounts)", ip, accounts)
        flagged += 1
    return flagged
