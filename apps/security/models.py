"""Security telemetry: anomalies, rate-limit trips and IP reputation."""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel


class AnomalySeverity(models.TextChoices):
    INFO = "info", "Informational"
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"
    CRITICAL = "critical", "Critical"


class SecurityEvent(TimeStampedModel):
    """A detected anomaly. Append-only; resolution is a flag, never a delete."""

    class Kind(models.TextChoices):
        NEW_DEVICE = "new_device", "Login from a new device"
        NEW_LOCATION = "new_location", "Login from a new location"
        IMPOSSIBLE_TRAVEL = "impossible_travel", "Impossible travel"
        CREDENTIAL_STUFFING = "credential_stuffing", "Credential stuffing pattern"
        BRUTE_FORCE = "brute_force", "Brute force attempt"
        RATE_LIMIT = "rate_limit", "Rate limit exceeded"
        SUSPICIOUS_IP = "suspicious_ip", "Request from a flagged IP"
        SESSION_HIJACK = "session_hijack", "Possible session hijack"
        MASS_ACTION = "mass_action", "Unusual volume of actions"
        PRIVILEGE_ESCALATION = "privilege_escalation", "Privilege escalation attempt"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        null=True, blank=True, related_name="security_events",
    )
    kind = models.CharField(max_length=24, choices=Kind.choices, db_index=True)
    severity = models.CharField(
        max_length=10, choices=AnomalySeverity.choices,
        default=AnomalySeverity.LOW, db_index=True,
    )
    description = models.CharField(max_length=400)
    risk_score = models.PositiveSmallIntegerField(default=0)

    ip_address = models.GenericIPAddressField(null=True, blank=True, db_index=True)
    user_agent = models.CharField(max_length=512, blank=True)
    device_fingerprint = models.CharField(max_length=128, blank=True)
    path = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    is_resolved = models.BooleanField(default=False, db_index=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "security_event"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["severity", "is_resolved"]),
        ]

    def __str__(self):
        return f"{self.kind} ({self.severity})"

    def resolve(self, note=""):
        self.is_resolved = True
        self.resolved_at = timezone.now()
        self.resolution_note = note[:255]
        self.save(update_fields=["is_resolved", "resolved_at", "resolution_note"])


class IPReputation(TimeStampedModel):
    """Rolling per-IP score. Feeds the rate limiter and anomaly detector."""

    ip_address = models.GenericIPAddressField(primary_key=True)
    score = models.SmallIntegerField(default=100, help_text="0 (hostile) to 100 (clean).")
    failed_logins = models.PositiveIntegerField(default=0)
    blocked_requests = models.PositiveIntegerField(default=0)
    accounts_seen = models.PositiveIntegerField(default=0)
    country = models.CharField(max_length=60, blank=True)
    is_blocked = models.BooleanField(default=False, db_index=True)
    blocked_until = models.DateTimeField(null=True, blank=True)
    notes = models.CharField(max_length=400, blank=True)
    last_seen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "security_ip_reputation"
        ordering = ["score"]

    def __str__(self):
        return f"{self.ip_address} ({self.score})"

    @property
    def is_currently_blocked(self):
        if not self.is_blocked:
            return False
        return not self.blocked_until or self.blocked_until > timezone.now()

    def penalise(self, points, note=""):
        self.score = max(self.score - points, 0)
        if note:
            self.notes = note[:400]
        if self.score <= 10 and not self.is_blocked:
            self.is_blocked = True
            self.blocked_until = timezone.now() + timezone.timedelta(hours=24)
        self.save()
        return self.score


class RateLimitBreach(TimeStampedModel):
    """Recorded whenever a limiter trips — the raw material for tuning."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scope = models.CharField(max_length=60, db_index=True)
    identifier = models.CharField(max_length=191, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    path = models.CharField(max_length=255, blank=True)
    limit = models.PositiveIntegerField(default=0)
    window_seconds = models.PositiveIntegerField(default=0)
    hits = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "security_rate_limit_breach"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.scope}:{self.identifier}"
