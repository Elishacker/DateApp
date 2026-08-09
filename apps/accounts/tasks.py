"""Background jobs owned by the accounts service."""
import logging

from celery import shared_task
from django.utils import timezone

from apps.common.events import Event, publish

from .models import AccountStatus, Device, User

logger = logging.getLogger(__name__)

DELETION_GRACE_DAYS = 30
STALE_ONLINE_MINUTES = 10


@shared_task(name="apps.accounts.tasks.purge_pending_deletions")
def purge_pending_deletions():
    """Hard-delete accounts past their 30-day grace period."""
    cutoff = timezone.now() - timezone.timedelta(days=DELETION_GRACE_DAYS)
    doomed = User.objects.filter(deletion_requested_at__lt=cutoff)
    count = 0
    for user in doomed:
        user_id = str(user.id)
        # Other services purge their own rows in response to this event.
        publish(Event.USER_DELETED, {"user_id": user_id, "scheduled": False}, actor_id=user_id)
        user.delete()
        count += 1
    logger.info("purged %d account(s)", count)
    return count


@shared_task(name="apps.accounts.tasks.clear_stale_presence")
def clear_stale_presence():
    """Flip 'online' off for sessions that vanished without a disconnect."""
    cutoff = timezone.now() - timezone.timedelta(minutes=STALE_ONLINE_MINUTES)
    return User.objects.filter(is_online=True, last_active_at__lt=cutoff).update(is_online=False)


@shared_task(name="apps.accounts.tasks.unlock_expired_lockouts")
def unlock_expired_lockouts():
    return User.objects.filter(
        locked_until__lt=timezone.now()
    ).update(locked_until=None, failed_login_attempts=0)


@shared_task(name="apps.accounts.tasks.prune_revoked_devices")
def prune_revoked_devices(days=90):
    cutoff = timezone.now() - timezone.timedelta(days=days)
    deleted, _ = Device.objects.filter(revoked_at__lt=cutoff).delete()
    return deleted


@shared_task(name="apps.accounts.tasks.reactivate_returning_user")
def reactivate_returning_user(user_id):
    User.objects.filter(id=user_id, status=AccountStatus.DEACTIVATED).update(
        status=AccountStatus.ACTIVE, deactivated_at=None, deletion_requested_at=None
    )
