"""Abuse reports, blocks and support tickets.

Blocking lives here rather than in accounts because a block is a safety action:
it is reported on, audited, and feeds the moderation queue.
"""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel
from apps.common.storage import report_evidence_path


class ReportReason(models.TextChoices):
    FAKE_PROFILE = "fake_profile", "Fake profile or catfish"
    HARASSMENT = "harassment", "Harassment or abuse"
    INAPPROPRIATE_PHOTOS = "inappropriate_photos", "Inappropriate photos"
    SCAM = "scam", "Scam or asking for money"
    UNDERAGE = "underage", "Appears to be under 18"
    SPAM = "spam", "Spam or advertising"
    OFF_PLATFORM = "off_platform", "Pushing to another app"
    HATE_SPEECH = "hate_speech", "Hate speech"
    THREAT = "threat", "Threats or violence"
    OTHER = "other", "Something else"


#: Reasons that jump the queue regardless of reporter trust.
URGENT_REASONS = {
    ReportReason.UNDERAGE, ReportReason.THREAT, ReportReason.HATE_SPEECH
}


class Report(TimeStampedModel):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        REVIEWING = "reviewing", "Under review"
        ACTIONED = "actioned", "Action taken"
        DISMISSED = "dismissed", "Dismissed"

    class Outcome(models.TextChoices):
        NONE = "none", "No action"
        WARNING = "warning", "Warning issued"
        CONTENT_REMOVED = "content_removed", "Content removed"
        SHADOW_BANNED = "shadow_banned", "Shadow banned"
        SUSPENDED = "suspended", "Account suspended"
        BANNED = "banned", "Account banned"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reports_made"
    )
    reported = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reports_received"
    )

    reason = models.CharField(max_length=24, choices=ReportReason.choices, db_index=True)
    description = models.TextField(max_length=2000, blank=True)
    evidence = models.ImageField(upload_to=report_evidence_path, blank=True, null=True)

    #: Optional pointer to the offending object, owned by another service.
    context_type = models.CharField(max_length=40, blank=True)
    context_id = models.UUIDField(null=True, blank=True)

    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.OPEN, db_index=True
    )
    outcome = models.CharField(
        max_length=16, choices=Outcome.choices, default=Outcome.NONE
    )
    is_urgent = models.BooleanField(default=False, db_index=True)

    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="reports_handled",
    )
    handled_at = models.DateTimeField(null=True, blank=True)
    moderator_note = models.TextField(blank=True)

    class Meta:
        db_table = "reports_report"
        ordering = ["-is_urgent", "-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["reported", "status"]),
        ]

    def __str__(self):
        return f"{self.reason} against {self.reported_id}"

    def save(self, *args, **kwargs):
        if self.reason in URGENT_REASONS:
            self.is_urgent = True
        super().save(*args, **kwargs)

    @property
    def is_open(self):
        return self.status in {self.Status.OPEN, self.Status.REVIEWING}

    def resolve(self, outcome, moderator=None, note=""):
        self.status = (
            self.Status.DISMISSED if outcome == self.Outcome.NONE else self.Status.ACTIONED
        )
        self.outcome = outcome
        self.handled_by = moderator
        self.handled_at = timezone.now()
        self.moderator_note = note
        self.save(update_fields=["status", "outcome", "handled_by",
                                 "handled_at", "moderator_note", "updated_at"])
        return self


class Block(TimeStampedModel):
    """A hard visibility barrier, honoured by discovery, chat and matching."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    blocker = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="blocks_made"
    )
    blocked = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="blocks_received"
    )
    reason = models.CharField(max_length=200, blank=True)
    #: True when the block was applied automatically alongside a report.
    from_report = models.BooleanField(default=False)

    class Meta:
        db_table = "reports_block"
        unique_together = [("blocker", "blocked")]
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["blocker"]),
            models.Index(fields=["blocked"]),
        ]

    def __str__(self):
        return f"{self.blocker_id} blocked {self.blocked_id}"


class SupportTicket(TimeStampedModel):
    class Category(models.TextChoices):
        ACCOUNT = "account", "Account"
        BILLING = "billing", "Billing"
        SAFETY = "safety", "Safety"
        TECHNICAL = "technical", "Technical"
        FEEDBACK = "feedback", "Feedback"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        WAITING = "waiting", "Waiting on member"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number = models.CharField(max_length=20, unique=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="support_tickets"
    )
    category = models.CharField(max_length=12, choices=Category.choices, default=Category.OTHER)
    subject = models.CharField(max_length=140)
    message = models.TextField(max_length=4000)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.OPEN, db_index=True
    )
    is_priority = models.BooleanField(default=False)

    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="support_assigned",
    )
    resolution = models.TextField(blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "reports_support_ticket"
        ordering = ["-is_priority", "-created_at"]

    def __str__(self):
        return f"{self.number}: {self.subject}"
