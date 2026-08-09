from django.contrib import admin

from .models import DailyMetric, FunnelSnapshot


@admin.register(DailyMetric)
class DailyMetricAdmin(admin.ModelAdmin):
    list_display = ("date", "metric", "dimension", "value")
    list_filter = ("metric",)
    search_fields = ("metric", "dimension")
    date_hierarchy = "date"


@admin.register(FunnelSnapshot)
class FunnelSnapshotAdmin(admin.ModelAdmin):
    list_display = ("date", "signups", "verified_email", "completed_onboarding",
                    "got_first_match", "subscribed")
    date_hierarchy = "date"
    readonly_fields = ("id", "created_at", "updated_at")
