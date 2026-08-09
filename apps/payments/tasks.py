"""Background jobs owned by the payments service."""
import logging

from celery import shared_task
from django.utils import timezone

from .models import Payment, PaymentStatus, WebhookEvent
from .services import PaymentService

logger = logging.getLogger(__name__)


@shared_task(name="apps.payments.tasks.reconcile_open_payments")
def reconcile_open_payments(minutes=10):
    """Poll providers for payments whose callback never arrived.

    This is the safety net that makes the whole flow robust: a lost webhook
    delays activation by minutes, it does not lose the sale.
    """
    cutoff = timezone.now() - timezone.timedelta(minutes=minutes)
    open_payments = Payment.objects.filter(
        status__in=[PaymentStatus.PENDING, PaymentStatus.PROCESSING],
        created_at__lt=cutoff,
    ).exclude(provider_reference="")[:200]

    reconciled = 0
    for payment in open_payments:
        try:
            PaymentService.poll_status(payment)
            reconciled += 1
        except Exception:  # noqa: BLE001 - one bad provider must not stop the sweep
            logger.exception("reconciliation failed for %s", payment.reference)
    logger.info("reconciled %d payment(s)", reconciled)
    return reconciled


@shared_task(name="apps.payments.tasks.expire_stale_payments")
def expire_stale_payments():
    return Payment.objects.filter(
        status__in=[PaymentStatus.PENDING, PaymentStatus.PROCESSING],
        expires_at__lt=timezone.now(),
    ).update(status=PaymentStatus.CANCELLED, failure_reason="Payment window expired.")


@shared_task(name="apps.payments.tasks.replay_failed_webhooks")
def replay_failed_webhooks(limit=50):
    """Re-process stored callbacks that failed the first time."""
    from .services import WebhookService

    import json

    stale = WebhookEvent.objects.filter(is_processed=False).exclude(error="")[:limit]
    replayed = 0
    for event in stale:
        try:
            WebhookService.receive(
                event.provider, json.dumps(event.payload).encode(), event.headers or {}
            )
            replayed += 1
        except Exception:  # noqa: BLE001
            logger.exception("webhook replay failed for %s", event.id)
    return replayed


@shared_task(name="apps.payments.tasks.prune_webhook_events")
def prune_webhook_events(days=90):
    cutoff = timezone.now() - timezone.timedelta(days=days)
    deleted, _ = WebhookEvent.objects.filter(
        created_at__lt=cutoff, is_processed=True
    ).delete()
    return deleted
