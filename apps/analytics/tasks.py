"""Background jobs owned by the analytics service."""
import logging

from celery import shared_task
from django.utils import timezone

from .services import CollectionService

logger = logging.getLogger(__name__)


@shared_task(name="apps.analytics.tasks.rollup_daily_metrics")
def rollup_daily_metrics(date=None):
    """Nightly collection for the previous day."""
    collected = CollectionService.collect(date)
    logger.info("rolled up %d metric(s)", len(collected))
    return len(collected)


@shared_task(name="apps.analytics.tasks.backfill_metrics")
def backfill_metrics(days=30):
    """Recompute the last N days — useful after adding a new metric."""
    today = timezone.now().date()
    for offset in range(1, days + 1):
        CollectionService.collect(today - timezone.timedelta(days=offset))
    return days
