"""Identity, device registry and account settings.

``accounts`` is the identity service. It owns *who someone is* and *what state
their account is in* — nothing about dating. Photos, bios and match criteria
belong to ``profiles``; credentials and tokens belong to ``authentication``.

Note ``avatar_url`` / ``display_age``: those are a **local read model**. The
profiles service owns the truth and publishes an event; accounts keeps a copy so
it can answer ``get_user_ref()`` without ever querying another service's tables.
That is the same denormalisation you would use across a network boundary.
"""
import uuid

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils import timezone

from apps.common.constants import VerificationLevel
from apps.common.models import TimeStampedModel
from apps.common.utils import calculate_age
from apps.common.validators import validate_phone, validate_username

from .managers import UserManager


class AccountStatus(models.TextChoices):
    PENDING = "pending", "Pending verification"
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"
    BANNED = "banned", "Banned"
    DEACTIVATED = "deactivated", "Deactivated by user"


class UserRole(models.TextChoices):
    MEMBER = "member", "Member"
    MODERATOR = "moderator", "Moderator"
    SUPPORT = "support", "Support agent"
    ANALYST = "analyst", "Analyst"
    ADMIN = "admin", "Administrator"


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    email = models.EmailField(unique=True, db_index=True)
    phone = models.CharField(
        max_length=20, unique=True, null=True, blank=True,
        validators=[validate_phone], db_index=True,
    )
    username = models.CharField(
        max_length=30, unique=True, validators=[validate_username], db_index=True
    )
    first_name = models.CharField(max_length=60, blank=True)
    last_name = models.CharField(max_length=60, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)

    role = models.CharField(max_length=20, choices=UserRole.choices, default=UserRole.MEMBER)
    status = models.CharField(
        max_length=20, choices=AccountStatus.choices,
        default=AccountStatus.PENDING, db_index=True,
    )

    # Verification flags. The verification service owns the evidence and the
    # workflow; accounts only mirrors the resulting badges.
    is_email_verified = models.BooleanField(default=False)
    is_phone_verified = models.BooleanField(default=False)
    is_photo_verified = models.BooleanField(default=False)
    is_identity_verified = models.BooleanField(default=False)
    verification_level = models.PositiveSmallIntegerField(
        choices=VerificationLevel.choices, default=VerificationLevel.NONE
    )

    # Security posture. Credentials themselves live in `authentication`.
    is_mfa_enabled = models.BooleanField(default=False)
    failed_login_attempts = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    password_changed_at = models.DateTimeField(null=True, blank=True)
    must_change_password = models.BooleanField(default=False)

    # Lifecycle
    has_completed_onboarding = models.BooleanField(default=False)
    onboarding_step = models.PositiveSmallIntegerField(default=1)
    last_active_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)
    is_online = models.BooleanField(default=False)
    deactivated_at = models.DateTimeField(null=True, blank=True)
    deletion_requested_at = models.DateTimeField(null=True, blank=True)

    # Read model projected from the profiles service (see module docstring).
    avatar_url = models.CharField(max_length=255, blank=True)

    # Django flags
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now, db_index=True)

    accepted_terms_at = models.DateTimeField(null=True, blank=True)
    marketing_opt_in = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    class Meta:
        db_table = "accounts_user"
        ordering = ["-date_joined"]
        indexes = [
            models.Index(fields=["status", "is_active"]),
            models.Index(fields=["-last_active_at"]),
        ]

    def __str__(self):
        return self.email

    # ---- derived properties ------------------------------------------------
    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip() or self.username

    def get_full_name(self):
        return self.full_name

    def get_short_name(self):
        return self.first_name or self.username

    @property
    def display_name(self):
        return self.first_name or self.username

    @property
    def age(self):
        return calculate_age(self.date_of_birth)

    @property
    def is_moderator(self):
        return self.role in {UserRole.MODERATOR, UserRole.ADMIN} or self.is_staff

    @property
    def is_banned(self):
        return self.status in {AccountStatus.BANNED, AccountStatus.SUSPENDED}

    @property
    def is_locked(self):
        return bool(self.locked_until and self.locked_until > timezone.now())

    @property
    def is_verified(self):
        return self.verification_level >= VerificationLevel.PHOTO

    @property
    def can_use_platform(self):
        return self.is_active and self.status == AccountStatus.ACTIVE and not self.is_locked

    # ---- state transitions -------------------------------------------------
    def recompute_verification_level(self):
        level = VerificationLevel.NONE
        if self.is_email_verified:
            level = VerificationLevel.EMAIL
        if self.is_phone_verified:
            level = VerificationLevel.PHONE
        if self.is_photo_verified:
            level = VerificationLevel.PHOTO
        if self.is_identity_verified:
            level = VerificationLevel.IDENTITY
        if self.verification_level != level:
            self.verification_level = level
            self.save(update_fields=["verification_level"])
        return level

    def touch_activity(self, ip=None):
        fields = ["last_active_at"]
        self.last_active_at = timezone.now()
        if ip:
            self.last_login_ip = ip
            fields.append("last_login_ip")
        self.save(update_fields=fields)

    def mark_online(self, online=True):
        self.is_online = online
        self.last_active_at = timezone.now()
        self.save(update_fields=["is_online", "last_active_at"])


class Device(TimeStampedModel):
    """A recognised browser or app installation.

    Owned by accounts because it is part of identity; the security service reads
    it through the accounts contract to score login anomalies.
    """

    class Platform(models.TextChoices):
        WEB = "web", "Web"
        ANDROID = "android", "Android"
        IOS = "ios", "iOS"
        UNKNOWN = "unknown", "Unknown"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="devices")
    fingerprint = models.CharField(max_length=128, db_index=True)
    name = models.CharField(max_length=120, blank=True)
    platform = models.CharField(max_length=20, choices=Platform.choices, default=Platform.UNKNOWN)
    user_agent = models.CharField(max_length=512, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    location = models.CharField(max_length=120, blank=True)
    push_token = models.CharField(max_length=255, blank=True)

    is_trusted = models.BooleanField(default=False)
    last_seen_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "accounts_device"
        unique_together = [("user", "fingerprint")]
        ordering = ["-last_seen_at"]

    def __str__(self):
        return f"{self.name or self.get_platform_display()} · {self.user_id}"

    @property
    def is_revoked(self):
        return self.revoked_at is not None

    def revoke(self):
        self.revoked_at = timezone.now()
        self.is_trusted = False
        self.save(update_fields=["revoked_at", "is_trusted"])

    def touch(self, ip=None):
        self.last_seen_at = timezone.now()
        fields = ["last_seen_at"]
        if ip:
            self.ip_address = ip
            fields.append("ip_address")
        self.save(update_fields=fields)


class UserSettings(TimeStampedModel):
    """Account-level preferences (not matching criteria — those are in profiles)."""

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="settings", primary_key=True
    )

    language = models.CharField(max_length=10, default="en")
    theme = models.CharField(
        max_length=10,
        choices=[("system", "System"), ("light", "Light"), ("dark", "Dark")],
        default="system",
    )

    email_notifications = models.BooleanField(default=True)
    push_notifications = models.BooleanField(default=True)
    sms_notifications = models.BooleanField(default=False)
    notify_on_match = models.BooleanField(default=True)
    notify_on_message = models.BooleanField(default=True)
    notify_on_like = models.BooleanField(default=True)

    show_online_status = models.BooleanField(default=True)
    show_distance = models.BooleanField(default=True)
    show_age = models.BooleanField(default=True)
    show_last_active = models.BooleanField(default=True)
    incognito_mode = models.BooleanField(default=False)
    read_receipts_enabled = models.BooleanField(default=True)

    class Meta:
        db_table = "accounts_user_settings"
        verbose_name_plural = "User settings"

    def __str__(self):
        return f"Settings for {self.user_id}"
