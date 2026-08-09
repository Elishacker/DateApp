"""Public contract of the analytics service."""
from apps.common.interface import ModuleInterface

from .models import DailyMetric, FunnelSnapshot
from .services import CollectionService, DashboardService, MetricService


class AnalyticsInterface(ModuleInterface):
    name = "analytics"
    depends_on = ("accounts", "likes", "matches", "chat", "payments",
                  "subscriptions", "moderation", "reports", "verification", "security")

    def record_metric(self, date, metric, value, dimension=""):
        row = MetricService.record(date, metric, value, dimension)
        return str(row.id)

    def get_series(self, metric, days=30, dimension=""):
        return MetricService.series(metric, days, dimension)

    def get_total(self, metric, days=30, dimension=""):
        return MetricService.total(metric, days, dimension)

    def get_dashboard(self, days=30):
        return DashboardService.overview(days)

    def get_funnel(self, date=None):
        snapshot = (
            FunnelSnapshot.objects.filter(date=date).first() if date
            else FunnelSnapshot.objects.first()
        )
        return snapshot.as_steps() if snapshot else []

    def collect_for(self, date=None):
        return CollectionService.collect(date)

    def available_metrics(self):
        return sorted(DailyMetric.objects.values_list("metric", flat=True).distinct())


service = AnalyticsInterface()
