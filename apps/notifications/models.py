"""Multi-channel notification delivery.

``notifications`` owns the in-app inbox and the outbound delivery ledger. It is
a pure consumer of events — no other module calls it to say "a match happened";
they publish, and this module decides who gets told, on which channel.
"""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import ServiceReference, TimeStampedModel


class NotificationKind(models.TextChoices):
    MATCH = "match", "New match"
    LIKE = "like", "Someone liked you"
    SUPER_LIKE = "super_like", "Super like"
    MESSAGE = "message", "New message"
    PROFILE_VIEW = "profile_view", "Profile view"
    VERIFICATION = "verification", "Verification update"
    SUBSCRIPTION = "subscription", "Subscription update"
    PAYMENT = "payment", "Payment update"
    SECURITY = "security", "Security alert"
    MODERATION = "moderation", "Moderation notice"
    SYSTEM = "system", "System"


class Channel(models.TextChoices):
    IN_APP = "in_app", "In-app"
    EMAIL = "email", "Email"
    PUSH = "push", "Push"
    SMS = "sms", "SMS"


class DeliveryStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SENT = "sent", "Sent"
    FAILED = "failed", "Failed"
    SUPPRESSED = "suppressed", "Suppressed by preferences"


class Notification(TimeStampedModel):
    """One in-app inbox entry."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    kind = models.CharField(max_length=20, choices=NotificationKind.choices, db_index=True)

    title = models.CharField(max_length=140)
    body = models.CharField(max_length=400, blank=True)
    action_url = models.CharField(max_length=255, blank=True)
    #: Sprite icon name (e.g. "shield-lock-fill"). Was sized for a single
    #: emoji; names are far longer, which SQLite tolerates and Postgres
    #: does not.
    icon = models.CharField(max_length=40, blank=True)

    # Who or what the notification is about — owned by other services.
    actor_id = ServiceReference("accounts", null=True, blank=True)
    actor_name = models.CharField(max_length=80, blank=True)
    actor_avatar_url = models.CharField(max_length=255, blank=True)
    object_id = models.UUIDField(null=True, blank=True)
    object_type = models.CharField(max_length=40, blank=True)

    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    in_inbox = models.BooleanField(
        default=True, db_index=True,
        help_text="Shown in the member's notification inbox. Operational "
                  "records are retained but excluded — see INBOX_KINDS.",
    )

    class Meta:
        db_table = "notifications_notification"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "in_inbox", "is_read", "-created_at"]),
            models.Index(fields=["user", "kind"]),
        ]

    def __str__(self):
        return f"{self.kind} for {self.user_id}"

    def mark_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=["is_read", "read_at"])


class DeliveryLog(TimeStampedModel):
    """Ledger of every outbound send — the basis for retries and debugging."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_deliveries"
    )
    notification = models.ForeignKey(
        Notification, on_delete=models.SET_NULL, null=True, blank=True, related_name="deliveries"
    )
    channel = models.CharField(max_length=10, choices=Channel.choices, db_index=True)
    status = models.CharField(
        max_length=12, choices=DeliveryStatus.choices,
        default=DeliveryStatus.PENDING, db_index=True,
    )
    destination = models.CharField(max_length=255, blank=True)
    template = models.CharField(max_length=60, blank=True)
    subject = models.CharField(max_length=200, blank=True)
    provider_reference = models.CharField(max_length=120, blank=True)
    error = models.CharField(max_length=400, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    sent_at = models.DateTimeField(null=True, blank=True)
    #: Template variables for transactional mail that has no inbox entry.
    context = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "notifications_delivery_log"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["channel", "status"])]

    def __str__(self):
        return f"{self.channel} → {self.destination} ({self.status})"

    def mark_sent(self, reference=""):
        self.status = DeliveryStatus.SENT
        self.sent_at = timezone.now()
        self.provider_reference = reference[:120]
        self.save(update_fields=["status", "sent_at", "provider_reference"])

    def mark_failed(self, error):
        self.status = DeliveryStatus.FAILED
        self.error = str(error)[:400]
        self.attempts += 1
        self.save(update_fields=["status", "error", "attempts"])
