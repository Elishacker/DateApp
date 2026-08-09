"""Background jobs owned by the profiles service."""
import logging

from celery import shared_task
from django.utils import timezone

from .models import Profile, ProfileView

logger = logging.getLogger(__name__)


@shared_task(name="apps.profiles.tasks.recompute_completion_scores")
def recompute_completion_scores(batch=500):
    """Nightly consistency pass over the denormalised completion score."""
    updated = 0
    for profile in Profile.objects.all().iterator(chunk_size=batch):
        before = profile.completion_score
        if profile.refresh_completion() != before:
            updated += 1
    logger.info("recomputed completion for %d profile(s)", updated)
    return updated


@shared_task(name="apps.profiles.tasks.expire_boosts")
def expire_boosts():
    return Profile.objects.filter(
        is_boosted_until__lt=timezone.now()
    ).update(is_boosted_until=None)


@shared_task(name="apps.profiles.tasks.prune_profile_views")
def prune_profile_views(days=90):
    cutoff = timezone.now() - timezone.timedelta(days=days)
    deleted, _ = ProfileView.objects.filter(created_at__lt=cutoff).delete()
    return deleted
