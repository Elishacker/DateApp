"""Background jobs owned by the matching service."""
import logging

from celery import shared_task
from django.utils import timezone

from apps.common.registry import services

from .models import CompatibilityScore, MatchingRun
from .services import MatchingService

logger = logging.getLogger(__name__)


@shared_task(name="apps.matching.tasks.precompute_for_user")
def precompute_for_user(user_id, pool_size=300):
    """Warm the score cache so the next feed request is instant."""
    excluded = {str(user_id)}
    excluded.update(services.likes.get_swiped_ids(user_id))
    excluded.update(services.matches.get_matched_user_ids(user_id))

    pool = services.accounts.list_dateable_ids(exclude_ids=list(excluded), limit=pool_size)
    rows = MatchingService.rank_candidates(user_id, pool, limit=100)
    logger.info("precomputed %d score(s) for %s", len(rows), user_id)
    return len(rows)


@shared_task(name="apps.matching.tasks.purge_expired_scores")
def purge_expired_scores():
    deleted, _ = CompatibilityScore.objects.filter(expires_at__lt=timezone.now()).delete()
    return deleted


@shared_task(name="apps.matching.tasks.invalidate_user_scores")
def invalidate_user_scores(user_id):
    MatchingService.invalidate_for(user_id)
    return True


@shared_task(name="apps.matching.tasks.prune_matching_runs")
def prune_matching_runs(days=30):
    cutoff = timezone.now() - timezone.timedelta(days=days)
    deleted, _ = MatchingRun.objects.filter(created_at__lt=cutoff).delete()
    return deleted
