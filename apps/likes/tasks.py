"""Background jobs owned by the likes service."""
from celery import shared_task
from django.utils import timezone

from .models import Like, SwipeQuota


@shared_task(name="apps.likes.tasks.reset_swipe_quotas")
def reset_swipe_quotas():
    """Midnight reset. The service also resets lazily, so this is belt-and-braces."""
    return SwipeQuota.objects.filter(
        reset_at__date__lt=timezone.now().date()
    ).update(likes_used=0, super_likes_used=0, rewinds_used=0, reset_at=timezone.now())


@shared_task(name="apps.likes.tasks.prune_passes")
def prune_passes(days=120):
    """Passes are re-showable after a few months, so old ones are dropped."""
    cutoff = timezone.now() - timezone.timedelta(days=days)
    deleted, _ = Like.objects.filter(kind="pass", created_at__lt=cutoff).delete()
    return deleted
