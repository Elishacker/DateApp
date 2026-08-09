"""Mutual connections.

A match is stored once with a canonical ordering (``user_low`` < ``user_high``
by UUID string) so a pair can never produce two rows regardless of who swiped
first. Chat references a match by UUID only — no foreign key across the
boundary.
"""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel


class MatchStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    UNMATCHED = "unmatched", "Unmatched"
    BLOCKED = "blocked", "Blocked"
    EXPIRED = "expired", "Expired"


class MatchOrigin(models.TextChoices):
    MUTUAL_LIKE = "mutual_like", "Mutual like"
    SUPER_LIKE = "super_like", "Super like"
    ADMIN = "admin", "Created by admin"


class Match(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Canonical ordering guarantees one row per pair.
    user_low = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="matches_as_low"
    )
    user_high = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="matches_as_high"
    )

    status = models.CharField(
        max_length=12, choices=MatchStatus.choices, default=MatchStatus.ACTIVE, db_index=True
    )
    origin = models.CharField(
        max_length=16, choices=MatchOrigin.choices, default=MatchOrigin.MUTUAL_LIKE
    )
    compatibility_score = models.PositiveSmallIntegerField(default=0)

    matched_at = models.DateTimeField(default=timezone.now, db_index=True)
    last_interaction_at = models.DateTimeField(null=True, blank=True, db_index=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    ended_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="matches_ended",
    )
    end_reason = models.CharField(max_length=140, blank=True)

    has_conversation = models.BooleanField(default=False)
    message_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "matches_match"
        unique_together = [("user_low", "user_high")]
        ordering = ["-matched_at"]
        indexes = [
            models.Index(fields=["user_low", "status"]),
            models.Index(fields=["user_high", "status"]),
            models.Index(fields=["status", "-last_interaction_at"]),
        ]

    def __str__(self):
        return f"{self.user_low_id} ↔ {self.user_high_id}"

    @property
    def is_active(self):
        return self.status == MatchStatus.ACTIVE

    def other_user_id(self, user_id):
        return self.user_high_id if str(self.user_low_id) == str(user_id) else self.user_low_id

    def involves(self, user_id):
        return str(user_id) in {str(self.user_low_id), str(self.user_high_id)}

    def end(self, by_user_id=None, reason="", status=MatchStatus.UNMATCHED):
        self.status = status
        self.ended_at = timezone.now()
        self.ended_by_id = by_user_id
        self.end_reason = reason[:140]
        self.save(update_fields=["status", "ended_at", "ended_by", "end_reason", "updated_at"])
        return self

    @staticmethod
    def order_pair(user_a, user_b):
        """Deterministic ordering so (a,b) and (b,a) map to the same row."""
        return (user_a, user_b) if str(user_a) < str(user_b) else (user_b, user_a)
