"""Background jobs owned by the authentication service."""
import logging

from celery import shared_task
from django.utils import timezone

from .models import ActiveSession, LoginAttempt, SecurityToken

logger = logging.getLogger(__name__)


@shared_task(name="apps.authentication.tasks.sweep_expired_tokens")
def sweep_expired_tokens():
    """Delete tokens that expired more than a day ago."""
    cutoff = timezone.now() - timezone.timedelta(days=1)
    deleted, _ = SecurityToken.objects.filter(expires_at__lt=cutoff).delete()
    logger.info("swept %d expired token(s)", deleted)
    return deleted


@shared_task(name="apps.authentication.tasks.expire_stale_sessions")
def expire_stale_sessions():
    return ActiveSession.objects.filter(
        expires_at__lt=timezone.now(), revoked_at__isnull=True
    ).update(revoked_at=timezone.now())


@shared_task(name="apps.authentication.tasks.prune_login_attempts")
def prune_login_attempts(days=180):
    """Retention limit on the login ledger."""
    cutoff = timezone.now() - timezone.timedelta(days=days)
    deleted, _ = LoginAttempt.objects.filter(created_at__lt=cutoff).delete()
    return deleted
