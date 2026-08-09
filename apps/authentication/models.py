"""Credentials, tokens and login telemetry.

``authentication`` owns *proof of identity*: verification tokens, reset tokens,
MFA secrets, social links and the login-attempt ledger. It holds a FK to the
user (shared identity kernel) and nothing else from other modules.

Every token is stored as a SHA-256 hash. The plaintext exists only inside the
outbound email/SMS, so a database disclosure yields nothing replayable.
"""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel
from apps.common.utils import hash_token


class TokenPurpose(models.TextChoices):
    EMAIL_VERIFICATION = "email_verification", "Email verification"
    PASSWORD_RESET = "password_reset", "Password reset"
    EMAIL_CHANGE = "email_change", "Email change"
    PHONE_OTP = "phone_otp", "Phone OTP"
    MFA_CHALLENGE = "mfa_challenge", "MFA challenge"
    DEVICE_CONFIRMATION = "device_confirmation", "New device confirmation"


class SecurityToken(TimeStampedModel):
    """Single-table, purpose-tagged, hashed, single-use token."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="security_tokens"
    )
    purpose = models.CharField(max_length=32, choices=TokenPurpose.choices, db_index=True)
    token_hash = models.CharField(max_length=64, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "auth_security_token"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["purpose", "token_hash"])]

    def __str__(self):
        return f"{self.get_purpose_display()} for {self.user_id}"

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    @property
    def is_used(self):
        return self.used_at is not None

    @property
    def is_valid(self):
        return not self.is_used and not self.is_expired and self.attempts < 5

    def matches(self, raw):
        return self.token_hash == hash_token(raw)

    def consume(self):
        self.used_at = timezone.now()
        self.save(update_fields=["used_at"])


class LoginAttempt(TimeStampedModel):
    """Append-only ledger. Feeds lockout, anomaly scoring and the audit trail."""

    class Outcome(models.TextChoices):
        SUCCESS = "success", "Success"
        BAD_CREDENTIALS = "bad_credentials", "Wrong password"
        UNKNOWN_USER = "unknown_user", "No such account"
        LOCKED = "locked", "Account locked"
        BANNED = "banned", "Account banned"
        MFA_REQUIRED = "mfa_required", "MFA challenge issued"
        MFA_FAILED = "mfa_failed", "MFA code rejected"
        RATE_LIMITED = "rate_limited", "Rate limited"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="login_attempts",
    )
    identifier = models.CharField(max_length=255, db_index=True)
    outcome = models.CharField(max_length=20, choices=Outcome.choices, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True, db_index=True)
    user_agent = models.CharField(max_length=512, blank=True)
    device_fingerprint = models.CharField(max_length=128, blank=True, db_index=True)
    location = models.CharField(max_length=120, blank=True)
    risk_score = models.PositiveSmallIntegerField(default=0)
    detail = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "auth_login_attempt"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["identifier", "-created_at"]),
            models.Index(fields=["ip_address", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.identifier} · {self.outcome}"

    @property
    def was_successful(self):
        return self.outcome == self.Outcome.SUCCESS


class MFASecret(TimeStampedModel):
    """TOTP enrolment plus one-time recovery codes (stored hashed)."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="mfa", primary_key=True,
    )
    secret = models.CharField(max_length=64)
    is_confirmed = models.BooleanField(default=False)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    recovery_codes = models.JSONField(default=list, blank=True)
    last_used_counter = models.BigIntegerField(default=0)

    class Meta:
        db_table = "auth_mfa_secret"
        verbose_name = "MFA secret"

    def __str__(self):
        return f"MFA for {self.user_id}"

    @property
    def recovery_codes_remaining(self):
        return len([c for c in self.recovery_codes if not c.get("used")])


class SocialAccount(TimeStampedModel):
    """Link between a Zynora account and an external identity provider."""

    class Provider(models.TextChoices):
        GOOGLE = "google", "Google"
        FACEBOOK = "facebook", "Facebook"
        APPLE = "apple", "Apple"
        X = "x", "X"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="social_accounts"
    )
    provider = models.CharField(max_length=20, choices=Provider.choices)
    provider_uid = models.CharField(max_length=191, db_index=True)
    email = models.EmailField(blank=True)
    extra_data = models.JSONField(default=dict, blank=True)
    connected_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "auth_social_account"
        unique_together = [("provider", "provider_uid")]

    def __str__(self):
        return f"{self.get_provider_display()} · {self.user_id}"


class ActiveSession(TimeStampedModel):
    """Server-side view of a live session so it can be revoked remotely."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="active_sessions"
    )
    session_key = models.CharField(max_length=64, blank=True, db_index=True)
    jti = models.CharField(max_length=64, blank=True, db_index=True,
                           help_text="JWT refresh token id, when the session is API-based.")
    device_fingerprint = models.CharField(max_length=128, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "auth_active_session"
        ordering = ["-last_seen_at"]

    def __str__(self):
        return f"session {self.id} · {self.user_id}"

    @property
    def is_active(self):
        if self.revoked_at:
            return False
        return not self.expires_at or self.expires_at > timezone.now()

    def revoke(self):
        self.revoked_at = timezone.now()
        self.save(update_fields=["revoked_at"])
