"""Cached compatibility scores.

Scoring a pair is cheap; scoring a whole candidate pool on every feed request is
not. This table is a materialised cache with a TTL, refreshed by a Celery job
and invalidated when either side changes their profile or preferences.
"""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel


class CompatibilityScore(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    seeker = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="scores_computed"
    )
    candidate = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="scores_received"
    )
    score = models.PositiveSmallIntegerField(db_index=True)
    distance_km = models.FloatField(null=True, blank=True)
    breakdown = models.JSONField(default=dict, blank=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        db_table = "matching_compatibility_score"
        unique_together = [("seeker", "candidate")]
        ordering = ["-score"]
        indexes = [models.Index(fields=["seeker", "-score"])]

    def __str__(self):
        return f"{self.seeker_id} → {self.candidate_id}: {self.score}"

    @property
    def is_fresh(self):
        return self.expires_at > timezone.now()


class MatchingRun(TimeStampedModel):
    """Audit record of a batch scoring run — how long it took, what it produced."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    seeker = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="matching_runs"
    )
    candidates_considered = models.PositiveIntegerField(default=0)
    candidates_scored = models.PositiveIntegerField(default=0)
    filtered_out = models.JSONField(default=dict, blank=True)
    duration_ms = models.PositiveIntegerField(default=0)
    top_score = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "matching_run"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Run for {self.seeker_id}: {self.candidates_scored} scored"
