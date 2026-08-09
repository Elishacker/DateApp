"""Identity assurance: email, phone, selfie and government ID.

Verification evidence is sensitive. Documents are stored under a private prefix,
are never exposed through a public serializer, and are purged once a decision is
made — the module keeps the *verdict*, not the identity document.
"""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel
from apps.common.storage import verification_document_path


class VerificationKind(models.TextChoices):
    EMAIL = "email", "Email address"
    PHONE = "phone", "Phone number"
    SELFIE = "selfie", "Selfie / photo verification"
    GOVERNMENT_ID = "government_id", "Government ID"


class VerificationStatus(models.TextChoices):
    PENDING = "pending", "Awaiting review"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    EXPIRED = "expired", "Expired"


class VerificationRequest(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="verification_requests"
    )
    kind = models.CharField(max_length=16, choices=VerificationKind.choices, db_index=True)
    status = models.CharField(
        max_length=10, choices=VerificationStatus.choices,
        default=VerificationStatus.PENDING, db_index=True,
    )

    #: The gesture the member was asked to reproduce, so a stock photo fails.
    challenge_pose = models.CharField(max_length=60, blank=True)
    document = models.ImageField(
        upload_to=verification_document_path, null=True, blank=True
    )
    document_number_hint = models.CharField(
        max_length=8, blank=True, help_text="Last characters only — never the full number."
    )
    target_value = models.CharField(
        max_length=191, blank=True, help_text="Phone or email being verified."
    )

    auto_confidence = models.PositiveSmallIntegerField(default=0)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="verifications_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=255, blank=True)
    attempts = models.PositiveSmallIntegerField(default=1)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "verification_request"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "kind", "status"]),
            models.Index(fields=["status", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.kind} verification for {self.user_id} ({self.status})"

    @property
    def is_pending(self):
        return self.status == VerificationStatus.PENDING

    @property
    def is_approved(self):
        return self.status == VerificationStatus.APPROVED

    def approve(self, moderator=None, confidence=None):
        self.status = VerificationStatus.APPROVED
        self.reviewed_by = moderator
        self.reviewed_at = timezone.now()
        if confidence is not None:
            self.auto_confidence = confidence
        self.save(update_fields=["status", "reviewed_by", "reviewed_at",
                                 "auto_confidence", "updated_at"])
        self.purge_document()
        return self

    def reject(self, reason="", moderator=None):
        self.status = VerificationStatus.REJECTED
        self.rejection_reason = reason[:255]
        self.reviewed_by = moderator
        self.reviewed_at = timezone.now()
        self.save(update_fields=["status", "rejection_reason", "reviewed_by",
                                 "reviewed_at", "updated_at"])
        self.purge_document()
        return self

    def purge_document(self):
        """Data minimisation: the decision is kept, the document is not."""
        if self.document:
            self.document.delete(save=False)
            self.document = None
            self.save(update_fields=["document"])


class VerificationBadge(TimeStampedModel):
    """Denormalised badge state, cheap for other services to read."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="verification_badge", primary_key=True,
    )
    email_verified_at = models.DateTimeField(null=True, blank=True)
    phone_verified_at = models.DateTimeField(null=True, blank=True)
    selfie_verified_at = models.DateTimeField(null=True, blank=True)
    identity_verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "verification_badge"

    def __str__(self):
        return f"Badges for {self.user_id}"

    @property
    def level(self):
        if self.identity_verified_at:
            return 4
        if self.selfie_verified_at:
            return 3
        if self.phone_verified_at:
            return 2
        if self.email_verified_at:
            return 1
        return 0

    @property
    def label(self):
        return {
            0: "Unverified", 1: "Email verified", 2: "Phone verified",
            3: "Photo verified", 4: "ID verified",
        }[self.level]
