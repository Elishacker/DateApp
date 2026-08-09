"""Immutable audit trail.

Every consequential action lands here. Rows are never updated or deleted by
application code — the admin blocks both — so the trail can be trusted during an
investigation or a dispute.
"""
import uuid

from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel


class AuditCategory(models.TextChoices):
    AUTHENTICATION = "authentication", "Authentication"
    ACCOUNT = "account", "Account"
    PROFILE = "profile", "Profile"
    ENGAGEMENT = "engagement", "Engagement"
    MESSAGING = "messaging", "Messaging"
    BILLING = "billing", "Billing"
    SAFETY = "safety", "Trust and safety"
    ADMIN = "admin", "Administration"
    SECURITY = "security", "Security"
    SYSTEM = "system", "System"


class AuditLog(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="audit_entries",
    )
    #: Kept as text so the trail survives the actor's account being deleted.
    actor_label = models.CharField(max_length=191, blank=True)

    action = models.CharField(max_length=80, db_index=True)
    category = models.CharField(
        max_length=20, choices=AuditCategory.choices,
        default=AuditCategory.SYSTEM, db_index=True,
    )
    description = models.CharField(max_length=400, blank=True)

    #: What was acted upon — owned by whichever service raised the event.
    object_type = models.CharField(max_length=60, blank=True, db_index=True)
    object_id = models.CharField(max_length=64, blank=True, db_index=True)
    target_user_id = models.UUIDField(null=True, blank=True, db_index=True)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    is_sensitive = models.BooleanField(
        default=False, db_index=True,
        help_text="Entries staff should not browse casually.",
    )

    class Meta:
        db_table = "audit_log"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["actor", "-created_at"]),
            models.Index(fields=["category", "-created_at"]),
            models.Index(fields=["object_type", "object_id"]),
        ]

    def __str__(self):
        return f"{self.action} by {self.actor_label or 'system'}"

    def save(self, *args, **kwargs):
        # Append-only: an existing row can never be rewritten.
        if self.pk and AuditLog.objects.filter(pk=self.pk).exists():
            raise ValueError("Audit log entries are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Audit log entries cannot be deleted.")
