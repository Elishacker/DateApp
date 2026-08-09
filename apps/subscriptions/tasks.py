"""Background jobs owned by the subscriptions service."""
import logging

from celery import shared_task
from django.utils import timezone

from .models import Subscription, SubscriptionStatus
from .services import SubscriptionService

logger = logging.getLogger(__name__)


@shared_task(name="apps.subscriptions.tasks.expire_due_subscriptions")
def expire_due_subscriptions():
    count = SubscriptionService.expire_due()
    logger.info("expired %d subscription(s)", count)
    return count


@shared_task(name="apps.subscriptions.tasks.reset_daily_quotas")
def reset_daily_quotas():
    """Delegates to the likes service, which owns the swipe counters."""
    from apps.common.registry import services

    return services.likes.reset_all_quotas()


@shared_task(name="apps.subscriptions.tasks.notify_expiring_soon")
def notify_expiring_soon(days=3):
    """Nudge members whose plan lapses in ``days`` days."""
    from apps.common.registry import services

    window_start = timezone.now() + timezone.timedelta(days=days)
    window_end = window_start + timezone.timedelta(days=1)

    due = Subscription.objects.filter(
        status=SubscriptionStatus.ACTIVE,
        auto_renew=False,
        expires_at__gte=window_start,
        expires_at__lt=window_end,
    ).select_related("plan")

    for subscription in due:
        services.notifications.notify(
            str(subscription.user_id), "subscription",
            title=f"Your {subscription.plan.name} plan ends soon",
            body=f"It expires in {days} days. Renew to keep your features.",
            action_url="/subscriptions/",
            channels=["email"],
        )
    return due.count()


@shared_task(name="apps.subscriptions.tasks.process_auto_renewals")
def process_auto_renewals():
    """Ask payments to charge the saved method for renewing subscriptions."""
    from apps.common.registry import services

    due = Subscription.objects.filter(
        status=SubscriptionStatus.ACTIVE,
        auto_renew=True,
        expires_at__lt=timezone.now() + timezone.timedelta(hours=24),
    ).select_related("plan")

    charged = 0
    for subscription in due:
        try:
            services.payments.charge_saved_method(
                user_id=str(subscription.user_id),
                amount=float(subscription.plan.price),
                currency=subscription.plan.currency,
                purpose="subscription_renewal",
                reference_id=str(subscription.id),
            )
            charged += 1
        except Exception:  # noqa: BLE001 - one failure must not stop the batch
            logger.exception("auto-renewal failed for %s", subscription.id)
    return charged
