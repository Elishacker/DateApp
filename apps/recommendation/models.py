"""Precomputed recommendation sets.

Recommendation is a *read model* built from the matching engine's output. It
stores nothing authoritative, which makes it safe to rebuild from scratch at any
time — and safe to replace with an ML service later.
"""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import ServiceReference, TimeStampedModel


class RecommendationSet(models.TextChoices):
    TOP_PICKS = "top_picks", "Top picks"
    NEARBY = "nearby", "People near you"
    MOST_COMPATIBLE = "most_compatible", "Most compatible"
    RECENTLY_ACTIVE = "recently_active", "Recently active"
    NEW_MEMBERS = "new_members", "New on Zynora"


class Recommendation(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recommendations"
    )
    candidate_id = ServiceReference("accounts")

    set_name = models.CharField(
        max_length=20, choices=RecommendationSet.choices,
        default=RecommendationSet.TOP_PICKS, db_index=True,
    )
    rank = models.PositiveSmallIntegerField(default=0)
    score = models.PositiveSmallIntegerField(default=0)
    reason = models.CharField(max_length=140, blank=True)
    distance_km = models.FloatField(null=True, blank=True)

    was_shown = models.BooleanField(default=False)
    shown_at = models.DateTimeField(null=True, blank=True)
    was_acted_on = models.BooleanField(default=False)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        db_table = "recommendation_recommendation"
        unique_together = [("user", "candidate_id", "set_name")]
        ordering = ["set_name", "rank"]
        indexes = [models.Index(fields=["user", "set_name", "rank"])]

    def __str__(self):
        return f"{self.set_name} #{self.rank} for {self.user_id}"

    @property
    def is_fresh(self):
        return self.expires_at > timezone.now()

    def mark_shown(self):
        if not self.was_shown:
            self.was_shown = True
            self.shown_at = timezone.now()
            self.save(update_fields=["was_shown", "shown_at"])
