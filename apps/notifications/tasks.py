"""Delivery workers for the notifications service."""
import logging

from celery import shared_task
from django.utils import timezone

from .models import DeliveryLog, DeliveryStatus, Notification
from .services import CHANNEL_HANDLERS, NotDeliverable

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3


@shared_task(
    name="apps.notifications.tasks.deliver_notification",
    bind=True, max_retries=MAX_ATTEMPTS, default_retry_delay=60,
)
def deliver_notification(self, log_id):
    """Send one queued delivery. Retries with backoff on transient failure."""
    log = DeliveryLog.objects.filter(id=log_id).select_related("notification").first()
    if not log:
        logger.warning("delivery log %s vanished", log_id)
        return False
    if log.status == DeliveryStatus.SENT:
        return True

    handler = CHANNEL_HANDLERS.get(log.channel)
    if not handler:
        log.mark_failed(f"No handler for channel '{log.channel}'.")
        return False

    try:
        reference = handler(log)
    except NotDeliverable as exc:
        # No route on this channel — nothing to retry, so record and move on.
        log.status = DeliveryStatus.SUPPRESSED
        log.error = str(exc)[:400]
        log.save(update_fields=["status", "error"])
        logger.debug("delivery %s suppressed: %s", log_id, exc)
        return False
    except Exception as exc:  # noqa: BLE001
        log.mark_failed(exc)
        logger.warning("delivery %s failed (attempt %s): %s", log_id, log.attempts, exc)
        if log.attempts < MAX_ATTEMPTS:
            raise self.retry(exc=exc)
        return False

    log.mark_sent(str(reference or ""))
    return True


@shared_task(name="apps.notifications.tasks.retry_failed_deliveries")
def retry_failed_deliveries():
    """Sweep for deliveries that exhausted their inline retries."""
    stale = DeliveryLog.objects.filter(
        status=DeliveryStatus.FAILED, attempts__lt=MAX_ATTEMPTS
    )[:200]
    for log in stale:
        deliver_notification.delay(str(log.id))
    return len(stale)


@shared_task(name="apps.notifications.tasks.prune_notifications")
def prune_notifications(days=90):
    cutoff = timezone.now() - timezone.timedelta(days=days)
    deleted, _ = Notification.objects.filter(created_at__lt=cutoff, is_read=True).delete()
    return deleted


@shared_task(name="apps.notifications.tasks.prune_delivery_logs")
def prune_delivery_logs(days=60):
    cutoff = timezone.now() - timezone.timedelta(days=days)
    deleted, _ = DeliveryLog.objects.filter(
        created_at__lt=cutoff, status=DeliveryStatus.SENT
    ).delete()
    return deleted
