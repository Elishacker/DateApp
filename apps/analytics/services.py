"""Metric collection and dashboard assembly.

Every number here is fetched through another module's contract. That is
deliberate: analytics must keep working when chat or payments moves to its own
database, and it must never be the reason a schema can't change.
"""
import logging
from datetime import timedelta

from django.utils import timezone

from apps.common.registry import services

from .models import DailyMetric, FunnelSnapshot

logger = logging.getLogger(__name__)


class MetricService:
    @staticmethod
    def record(date, metric, value, dimension="", metadata=None):
        row, _ = DailyMetric.objects.update_or_create(
            date=date, metric=metric, dimension=dimension,
            defaults={"value": value, "metadata": metadata or {}},
        )
        return row

    @staticmethod
    def series(metric, days=30, dimension=""):
        """Chart-ready series: a value for every day, gaps filled with zero."""
        end = timezone.now().date()
        start = end - timedelta(days=days - 1)

        rows = {
            r.date: float(r.value)
            for r in DailyMetric.objects.filter(
                metric=metric, dimension=dimension, date__gte=start, date__lte=end
            )
        }
        return [
            {"date": (start + timedelta(days=offset)).isoformat(),
             "value": rows.get(start + timedelta(days=offset), 0.0)}
            for offset in range(days)
        ]

    @staticmethod
    def total(metric, days=30, dimension=""):
        return sum(point["value"] for point in MetricService.series(metric, days, dimension))


class CollectionService:
    """Nightly gather. One call per module contract, nothing more."""

    @staticmethod
    def collect(date=None):
        date = date or (timezone.now().date() - timedelta(days=1))
        since = timezone.make_aware(
            timezone.datetime.combine(date, timezone.datetime.min.time())
        )
        until = since + timedelta(days=1)

        collected = {}

        likes = services.likes.daily_stats(since=since)
        collected.update({
            "likes": likes["likes"],
            "super_likes": likes["super_likes"],
            "passes": likes["passes"],
        })

        matches = services.matches.daily_stats(since=since)
        collected.update({
            "matches": matches["matches"],
            "matches_with_conversation": matches["with_conversation"],
            "active_matches": matches["active"],
        })

        chat = services.chat.daily_stats(since=since)
        collected.update({
            "messages": chat["messages"],
            "active_conversations": chat["conversations_active"],
            "flagged_messages": chat["flagged"],
        })

        revenue = services.payments.revenue_stats(since=since)
        collected.update({
            "revenue_gross": revenue["gross"],
            "revenue_net": revenue["net"],
            "transactions": revenue["transactions"],
        })

        subscriptions = services.subscriptions.revenue_stats(since=since)
        collected["new_subscriptions"] = subscriptions["subscriptions"]
        collected["active_subscriptions"] = subscriptions["active"]

        moderation = services.moderation.stats(since=since)
        collected.update({
            "moderation_cases": moderation["cases"],
            "moderation_rejected": moderation["rejected"],
            "shadow_banned": moderation["shadow_banned"],
        })

        collected["open_reports"] = services.reports.open_report_count()

        for metric, value in collected.items():
            MetricService.record(date, metric, value)

        CollectionService._snapshot_funnel(date, since, until)
        logger.info("collected %d metric(s) for %s", len(collected), date)
        return collected

    @staticmethod
    def _snapshot_funnel(date, since, until):
        """Funnel counts come from the modules that own each step."""
        from django.contrib.auth import get_user_model

        User = get_user_model()
        cohort = User.objects.filter(date_joined__gte=since, date_joined__lt=until)
        cohort_ids = list(cohort.values_list("id", flat=True))

        if not cohort_ids:
            FunnelSnapshot.objects.update_or_create(date=date, defaults={})
            return

        FunnelSnapshot.objects.update_or_create(
            date=date,
            defaults={
                "signups": len(cohort_ids),
                "verified_email": cohort.filter(is_email_verified=True).count(),
                "completed_onboarding": cohort.filter(
                    has_completed_onboarding=True
                ).count(),
                "sent_first_like": sum(
                    1 for uid in cohort_ids
                    if services.likes.get_swiped_ids(str(uid))
                ),
                "got_first_match": sum(
                    1 for uid in cohort_ids
                    if services.matches.count_matches(str(uid))
                ),
                "sent_first_message": sum(
                    1 for uid in cohort_ids
                    if services.chat.count_unread_messages(str(uid)) >= 0
                    and services.matches.count_matches(str(uid)) > 0
                ),
                "subscribed": sum(
                    1 for uid in cohort_ids
                    if services.subscriptions.is_premium(str(uid))
                ),
            },
        )


class DashboardService:
    """Assembles the admin dashboard. All formatting done here, not in the template."""

    @staticmethod
    def overview(days=30):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        now = timezone.now()
        today = now.date()

        return {
            "generated_at": now,
            "tiles": DashboardService._tiles(User, now, days),
            "charts": {
                "matches": MetricService.series("matches", days),
                "messages": MetricService.series("messages", days),
                "revenue": MetricService.series("revenue_gross", days),
                "likes": MetricService.series("likes", days),
            },
            "funnel": DashboardService._funnel(today),
            "safety": {
                "open_reports": services.reports.open_report_count(),
                "moderation_queue": services.moderation.queue_stats(),
                "verification_queue": services.verification.stats(),
                "security": services.security.dashboard_stats(),
            },
            "revenue": services.payments.revenue_stats(
                since=now - timedelta(days=days)
            ),
        }

    @staticmethod
    def _tiles(User, now, days):
        since = now - timedelta(days=days)
        total_users = User.objects.count()
        new_users = User.objects.filter(date_joined__gte=since).count()
        active_users = User.objects.filter(
            last_active_at__gte=now - timedelta(days=7)
        ).count()

        return [
            {"key": "members", "label": "Total members", "value": total_users,
             "sub": f"{new_users} new in {days} days"},
            {"key": "active", "label": "Active this week", "value": active_users,
             "sub": DashboardService._percent(active_users, total_users)},
            {"key": "online", "label": "Online now",
             "value": User.objects.filter(is_online=True).count(), "sub": "live"},
            {"key": "matches", "label": f"Matches ({days}d)",
             "value": int(MetricService.total("matches", days)), "sub": ""},
            {"key": "messages", "label": f"Messages ({days}d)",
             "value": int(MetricService.total("messages", days)), "sub": ""},
            {"key": "revenue", "label": f"Revenue ({days}d)",
             "value": round(MetricService.total("revenue_gross", days), 2),
             "sub": "gross"},
        ]

    @staticmethod
    def _funnel(today):
        snapshot = FunnelSnapshot.objects.filter(date__lte=today).first()
        return snapshot.as_steps() if snapshot else []

    @staticmethod
    def _percent(part, whole):
        return f"{round(part / whole * 100, 1)}% of members" if whole else "—"
