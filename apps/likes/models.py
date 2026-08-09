"""Swipe intents: like, super like, pass and rewind.

``likes`` records *intent only*. It never creates a match — it publishes
``LIKE_SENT`` and the matches service decides whether reciprocity exists. That
split is what lets likes and matches scale independently.
"""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel


class LikeType(models.TextChoices):
    LIKE = "like", "Like"
    SUPER_LIKE = "super_like", "Super like"
    PASS = "pass", "Pass"


class Like(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="likes_sent"
    )
    receiver = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="likes_received"
    )
    kind = models.CharField(
        max_length=12, choices=LikeType.choices, default=LikeType.LIKE, db_index=True
    )
    message = models.CharField(
        max_length=200, blank=True, help_text="Optional note attached to a super like."
    )
    source = models.CharField(max_length=30, default="discovery")
    #: Compatibility score at the moment of the swipe — useful for tuning the engine.
    score_at_swipe = models.PositiveSmallIntegerField(null=True, blank=True)
    is_rewound = models.BooleanField(default=False, db_index=True)
    seen_by_receiver = models.BooleanField(default=False, db_index=True)

    class Meta:
        db_table = "likes_like"
        unique_together = [("sender", "receiver")]
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["receiver", "kind", "seen_by_receiver"]),
            models.Index(fields=["sender", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.sender_id} {self.kind} {self.receiver_id}"

    @property
    def is_positive(self):
        return self.kind in {LikeType.LIKE, LikeType.SUPER_LIKE}


class SwipeQuota(TimeStampedModel):
    """Daily counters. Reset by a Celery beat job at midnight.

    Kept here rather than in subscriptions because the *counting* is a likes
    concern; subscriptions only supplies the limit.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="swipe_quota", primary_key=True,
    )
    likes_used = models.PositiveSmallIntegerField(default=0)
    super_likes_used = models.PositiveSmallIntegerField(default=0)
    rewinds_used = models.PositiveSmallIntegerField(default=0)
    reset_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "likes_swipe_quota"

    def __str__(self):
        return f"Quota for {self.user_id}"

    def reset(self):
        self.likes_used = 0
        self.super_likes_used = 0
        self.rewinds_used = 0
        self.reset_at = timezone.now()
        self.save(update_fields=["likes_used", "super_likes_used", "rewinds_used", "reset_at"])
