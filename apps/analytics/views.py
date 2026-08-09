"""Analytics dashboard (staff only)."""
import json

from django.views.generic import TemplateView

from apps.common.constants import Capability
from apps.common.mixins import CapabilityRequiredMixin

from .services import DashboardService, MetricService


class DashboardView(CapabilityRequiredMixin, TemplateView):
    required_capability = Capability.VIEW_ANALYTICS

    template_name = "analytics/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        days = int(self.request.GET.get("days", 30))
        days = days if days in {7, 30, 90} else 30

        overview = DashboardService.overview(days)
        context.update(overview)

        # Charts are drawn by static/js/charts.js; the data is serialised here
        # so the template contains no logic, only a data attribute.
        context["chart_data_json"] = json.dumps(overview["charts"])
        context["days"] = days
        context["range_options"] = [
            {"value": value, "label": label, "is_active": value == days}
            for value, label in ((7, "7 days"), (30, "30 days"), (90, "90 days"))
        ]
        return context


class MetricDetailView(CapabilityRequiredMixin, TemplateView):
    required_capability = Capability.VIEW_ANALYTICS

    template_name = "analytics/metric.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        metric = self.kwargs["metric"]
        days = int(self.request.GET.get("days", 90))

        series = MetricService.series(metric, days)
        values = [point["value"] for point in series]

        context["metric"] = metric
        context["metric_label"] = metric.replace("_", " ").title()
        context["series_json"] = json.dumps(series)
        context["total"] = round(sum(values), 2)
        context["average"] = round(sum(values) / len(values), 2) if values else 0
        context["peak"] = max(values) if values else 0
        context["days"] = days
        return context
