"""Background jobs owned by the recommendation service."""
import logging

from celery import shared_task
from django.utils import timezone

from .models import Recommendation
from .services import RecommendationService

logger = logging.getLogger(__name__)


@shared_task(name="apps.recommendation.tasks.refresh_for_user")
def refresh_for_user(user_id):
    return RecommendationService.build_all(user_id)


@shared_task(name="apps.recommendation.tasks.refresh_all_top_picks")
def refresh_all_top_picks(batch=500):
    """Nightly rebuild for members who were active in the last week."""
    from django.contrib.auth import get_user_model

    cutoff = timezone.now() - timezone.timedelta(days=7)
    active = get_user_model().objects.dateable().filter(
        last_active_at__gte=cutoff
    ).values_list("id", flat=True)[:batch]

    for user_id in active:
        refresh_for_user.delay(str(user_id))
    logger.info("queued recommendation refresh for %d member(s)", len(active))
    return len(active)


@shared_task(name="apps.recommendation.tasks.purge_expired")
def purge_expired():
    deleted, _ = Recommendation.objects.filter(expires_at__lt=timezone.now()).delete()
    return deleted
