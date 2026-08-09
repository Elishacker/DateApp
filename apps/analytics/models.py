"""Metric roll-ups.

``analytics`` stores only *aggregates*. It never reads another service's tables
directly — a nightly job asks each module's contract for its own numbers, which
is what keeps the dashboard working after any module is extracted.
"""
import uuid

from django.db import models

from apps.common.models import TimeStampedModel


class DailyMetric(TimeStampedModel):
    """One row per day per metric. Idempotent: re-running a day overwrites it."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    date = models.DateField(db_index=True)
    metric = models.CharField(max_length=60, db_index=True)
    value = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    dimension = models.CharField(
        max_length=60, blank=True,
        help_text="Optional breakdown key, e.g. a plan code or provider.",
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "analytics_daily_metric"
        unique_together = [("date", "metric", "dimension")]
        ordering = ["-date", "metric"]
        indexes = [models.Index(fields=["metric", "-date"])]

    def __str__(self):
        return f"{self.date} {self.metric}={self.value}"


class FunnelSnapshot(TimeStampedModel):
    """Conversion funnel captured daily: signup → onboarded → match → paid."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    date = models.DateField(unique=True, db_index=True)

    signups = models.PositiveIntegerField(default=0)
    verified_email = models.PositiveIntegerField(default=0)
    completed_onboarding = models.PositiveIntegerField(default=0)
    sent_first_like = models.PositiveIntegerField(default=0)
    got_first_match = models.PositiveIntegerField(default=0)
    sent_first_message = models.PositiveIntegerField(default=0)
    subscribed = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "analytics_funnel_snapshot"
        ordering = ["-date"]

    def __str__(self):
        return f"Funnel {self.date}"

    def as_steps(self):
        """Render-ready funnel rows with conversion percentages."""
        stages = [
            ("Signed up", self.signups),
            ("Verified email", self.verified_email),
            ("Completed onboarding", self.completed_onboarding),
            ("Sent a like", self.sent_first_like),
            ("Got a match", self.got_first_match),
            ("Sent a message", self.sent_first_message),
            ("Subscribed", self.subscribed),
        ]
        top = stages[0][1] or 1
        rows = []
        previous = None
        for label, count in stages:
            rows.append({
                "label": label,
                "count": count,
                "percent_of_total": round(count / top * 100, 1),
                "percent_of_previous": (
                    round(count / previous * 100, 1) if previous else 100.0
                ),
            })
            previous = count or None
        return rows
