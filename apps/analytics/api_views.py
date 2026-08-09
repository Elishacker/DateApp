"""Analytics REST endpoints (staff only)."""
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.common.mixins import ServiceResponseMixin
from apps.common.permissions import CanViewAnalytics
from apps.common.registry import services


class DashboardAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated, CanViewAnalytics]

    def get(self, request):
        days = int(request.query_params.get("days", 30))
        data = services.analytics.get_dashboard(days if days in {7, 30, 90} else 30)
        # ``generated_at`` is a datetime; the rest is already JSON-safe.
        data["generated_at"] = data["generated_at"].isoformat()
        return self.ok(data)


class MetricSeriesAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated, CanViewAnalytics]

    def get(self, request, metric):
        days = min(int(request.query_params.get("days", 30)), 365)
        return self.ok({
            "metric": metric,
            "days": days,
            "series": services.analytics.get_series(metric, days),
            "total": services.analytics.get_total(metric, days),
        })


class MetricListAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated, CanViewAnalytics]

    def get(self, request):
        return self.ok({"metrics": services.analytics.available_metrics()})
