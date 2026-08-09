"""Content safety: banned terms, automated screening and human review.

``moderation`` never edits another module's data directly. It reaches a verdict
and publishes ``CONTENT_FLAGGED``; the owning module (profiles, chat) applies it.
"""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import ServiceReference, TimeStampedModel


class Severity(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"
    CRITICAL = "critical", "Critical"


class BannedTerm(TimeStampedModel):
    """Word / phrase list applied to bios, messages and headlines."""

    class Action(models.TextChoices):
        FLAG = "flag", "Flag for review"
        MASK = "mask", "Mask the term"
        BLOCK = "block", "Block the content"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    term = models.CharField(max_length=80, unique=True, db_index=True)
    category = models.CharField(max_length=40, default="abuse")
    action = models.CharField(max_length=8, choices=Action.choices, default=Action.FLAG)
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.MEDIUM)
    is_regex = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True, db_index=True)
    hit_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "moderation_banned_term"
        ordering = ["term"]

    def __str__(self):
        return self.term


class ModerationCase(TimeStampedModel):
    """A single piece of content awaiting or having received a decision."""

    class Status(models.TextChoices):
        PENDING = "pending", "Awaiting review"
        AUTO_APPROVED = "auto_approved", "Auto-approved"
        AUTO_REJECTED = "auto_rejected", "Auto-rejected"
        APPROVED = "approved", "Approved by moderator"
        REJECTED = "rejected", "Rejected by moderator"
        ESCALATED = "escalated", "Escalated"

    class ObjectType(models.TextChoices):
        PROFILE_PHOTO = "profile_photo", "Profile photo"
        PROFILE_TEXT = "profile_text", "Profile text"
        MESSAGE = "message", "Chat message"
        VERIFICATION_PHOTO = "verification_photo", "Verification photo"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner_id = ServiceReference("accounts")
    object_type = models.CharField(max_length=24, choices=ObjectType.choices, db_index=True)
    object_id = models.UUIDField(db_index=True)

    content_snapshot = models.TextField(blank=True)
    content_url = models.CharField(max_length=255, blank=True)

    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.LOW)
    reasons = models.JSONField(default=list, blank=True)
    risk_score = models.PositiveSmallIntegerField(default=0)

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="moderation_reviews",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=400, blank=True)

    class Meta:
        db_table = "moderation_case"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["object_type", "object_id"]),
        ]

    def __str__(self):
        return f"{self.object_type} {self.object_id} ({self.status})"

    @property
    def is_resolved(self):
        return self.status != self.Status.PENDING

    @property
    def was_approved(self):
        return self.status in {self.Status.AUTO_APPROVED, self.Status.APPROVED}

    def resolve(self, approved, moderator=None, note=""):
        if moderator:
            self.status = self.Status.APPROVED if approved else self.Status.REJECTED
            self.reviewed_by = moderator
        else:
            self.status = self.Status.AUTO_APPROVED if approved else self.Status.AUTO_REJECTED
        self.reviewed_at = timezone.now()
        self.review_note = note[:400]
        self.save(update_fields=["status", "reviewed_by", "reviewed_at",
                                 "review_note", "updated_at"])
        return self


class TrustScore(TimeStampedModel):
    """Running per-member risk signal used to prioritise review queues."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="trust_score", primary_key=True,
    )
    score = models.SmallIntegerField(
        default=100, help_text="0 (untrusted) to 100 (fully trusted)."
    )
    flags_received = models.PositiveIntegerField(default=0)
    reports_received = models.PositiveIntegerField(default=0)
    content_rejected = models.PositiveIntegerField(default=0)
    is_shadow_banned = models.BooleanField(default=False, db_index=True)
    shadow_banned_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "moderation_trust_score"

    def __str__(self):
        return f"Trust {self.score} for {self.user_id}"

    @property
    def band(self):
        if self.score >= 80:
            return "trusted"
        if self.score >= 50:
            return "normal"
        if self.score >= 25:
            return "watch"
        return "high_risk"

    def penalise(self, points, reason=""):
        self.score = max(self.score - points, 0)
        if reason:
            self.notes = f"{timezone.now():%Y-%m-%d} {reason}\n{self.notes}"[:4000]
        # Falling below the floor hides the member without telling them —
        # deliberate, and logged for the audit trail.
        if self.score < 15 and not self.is_shadow_banned:
            self.is_shadow_banned = True
            self.shadow_banned_at = timezone.now()
        self.save()
        return self.score
