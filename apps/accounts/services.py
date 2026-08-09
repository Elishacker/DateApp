"""Accounts business logic. Private to the module — callers use ``interface``."""
import logging

from django.db import transaction
from django.utils import timezone

from apps.common.events import Event, publish
from apps.common.exceptions import NotFound, ValidationError

from .models import AccountStatus, Device, User, UserSettings

logger = logging.getLogger(__name__)


class AccountService:
    """Creation and lifecycle transitions for a member account."""

    @staticmethod
    @transaction.atomic
    def create_account(*, email, username, password, first_name="", date_of_birth=None,
                       phone=None, accepted_terms=False, marketing_opt_in=False):
        email = (email or "").strip().lower()
        username = (username or "").strip().lower()

        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("An account with this email already exists.", field="email")
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError("That username is taken.", field="username")
        if phone and User.objects.filter(phone=phone).exists():
            raise ValidationError("That phone number is already in use.", field="phone")
        if not accepted_terms:
            raise ValidationError("You must accept the Terms of Service.", field="accepted_terms")

        user = User.objects.create_user(
            email=email,
            username=username,
            password=password,
            first_name=first_name,
            date_of_birth=date_of_birth,
            phone=phone or None,
            accepted_terms_at=timezone.now(),
            marketing_opt_in=marketing_opt_in,
            status=AccountStatus.PENDING,
        )
        UserSettings.objects.create(user=user)

        # Downstream modules (profiles, onboarding, notifications, analytics,
        # audit) react to this — accounts does not know they exist.
        publish(Event.USER_REGISTERED, {
            "user_id": str(user.id),
            "email": user.email,
            "username": user.username,
            "first_name": user.first_name,
            "date_of_birth": str(user.date_of_birth) if user.date_of_birth else None,
        }, actor_id=user.id)

        logger.info("account created %s", user.id)
        return user

    @staticmethod
    def get(user_id):
        try:
            return User.objects.get(id=user_id)
        except (User.DoesNotExist, ValueError, TypeError) as exc:
            raise NotFound("That account does not exist.") from exc

    @staticmethod
    def activate(user_id):
        user = AccountService.get(user_id)
        user.status = AccountStatus.ACTIVE
        user.is_active = True
        user.save(update_fields=["status", "is_active"])
        publish(Event.USER_ACTIVATED, {"user_id": str(user.id)}, actor_id=user.id)
        return user

    @staticmethod
    def deactivate(user_id, reason=""):
        """Reversible self-service pause: hidden everywhere, data retained."""
        user = AccountService.get(user_id)
        user.status = AccountStatus.DEACTIVATED
        user.is_online = False
        user.deactivated_at = timezone.now()
        user.save(update_fields=["status", "is_online", "deactivated_at"])
        publish(Event.USER_DEACTIVATED, {"user_id": str(user.id), "reason": reason}, actor_id=user.id)
        return user

    @staticmethod
    def reactivate(user_id):
        user = AccountService.get(user_id)
        if user.status != AccountStatus.DEACTIVATED:
            raise ValidationError("This account is not deactivated.")
        user.status = AccountStatus.ACTIVE
        user.deactivated_at = None
        user.save(update_fields=["status", "deactivated_at"])
        publish(Event.USER_ACTIVATED, {"user_id": str(user.id)}, actor_id=user.id)
        return user

    @staticmethod
    def ban(user_id, *, reason, permanent=True, actor_id=None):
        user = AccountService.get(user_id)
        user.status = AccountStatus.BANNED if permanent else AccountStatus.SUSPENDED
        user.is_online = False
        user.save(update_fields=["status", "is_online"])
        publish(Event.USER_BANNED, {
            "user_id": str(user.id), "reason": reason, "permanent": permanent,
        }, actor_id=actor_id or user.id)
        return user

    @staticmethod
    def request_deletion(user_id):
        """Soft schedule: 30-day grace period before the purge task runs."""
        user = AccountService.get(user_id)
        user.deletion_requested_at = timezone.now()
        user.status = AccountStatus.DEACTIVATED
        user.is_online = False
        user.save(update_fields=["deletion_requested_at", "status", "is_online"])
        publish(Event.USER_DELETED, {"user_id": str(user.id), "scheduled": True}, actor_id=user.id)
        return user

    @staticmethod
    def update_avatar_projection(user_id, avatar_url):
        """Called by the event handler when profiles changes a primary photo."""
        User.objects.filter(id=user_id).update(avatar_url=avatar_url or "")

    @staticmethod
    def set_verification_flag(user_id, flag, value=True):
        allowed = {"is_email_verified", "is_phone_verified",
                   "is_photo_verified", "is_identity_verified"}
        if flag not in allowed:
            raise ValidationError(f"Unknown verification flag '{flag}'.")
        user = AccountService.get(user_id)
        setattr(user, flag, value)
        user.save(update_fields=[flag])
        user.recompute_verification_level()
        return user


class DeviceService:
    """Device registry used for trust decisions and push delivery."""

    @staticmethod
    def register(user, *, fingerprint, user_agent="", ip=None, platform=None, name=""):
        if not fingerprint:
            return None
        platform = platform or DeviceService.detect_platform(user_agent)
        device, created = Device.objects.get_or_create(
            user=user,
            fingerprint=fingerprint,
            defaults={
                "user_agent": user_agent,
                "ip_address": ip,
                "platform": platform,
                "name": name or DeviceService.describe(user_agent),
                # First device seen at signup is trusted; later ones must be
                # confirmed, which is what makes anomaly alerts meaningful.
                "is_trusted": not Device.objects.filter(user=user).exists(),
            },
        )
        if not created:
            device.last_seen_at = timezone.now()
            device.ip_address = ip or device.ip_address
            device.user_agent = user_agent or device.user_agent
            device.revoked_at = None
            device.save(update_fields=["last_seen_at", "ip_address", "user_agent", "revoked_at"])
        return device

    @staticmethod
    def detect_platform(user_agent):
        agent = (user_agent or "").lower()
        if "android" in agent:
            return Device.Platform.ANDROID
        if any(token in agent for token in ("iphone", "ipad", "ios")):
            return Device.Platform.IOS
        if agent:
            return Device.Platform.WEB
        return Device.Platform.UNKNOWN

    @staticmethod
    def describe(user_agent):
        agent = (user_agent or "").lower()
        browser = next((b for b in ("edg", "chrome", "firefox", "safari") if b in agent), "browser")
        system = next((s for s in ("windows", "mac", "linux", "android", "iphone") if s in agent), "device")
        return f"{browser.title()} on {system.title()}"[:120]

    @staticmethod
    def revoke(user, device_id):
        try:
            device = Device.objects.get(id=device_id, user=user)
        except Device.DoesNotExist as exc:
            raise NotFound("Device not found.") from exc
        device.revoke()
        return device

    @staticmethod
    def trust(user, device_id):
        Device.objects.filter(id=device_id, user=user).update(is_trusted=True, revoked_at=None)

    @staticmethod
    def list_for(user):
        return Device.objects.filter(user=user).order_by("-last_seen_at")

    @staticmethod
    def push_tokens_for(user_id):
        return list(
            Device.objects.filter(user_id=user_id, revoked_at__isnull=True)
            .exclude(push_token="")
            .values_list("push_token", flat=True)
        )


class SettingsService:
    @staticmethod
    def get_or_create(user):
        settings_row, _ = UserSettings.objects.get_or_create(user=user)
        return settings_row

    @staticmethod
    def update(user, **fields):
        settings_row = SettingsService.get_or_create(user)
        editable = {f.name for f in UserSettings._meta.fields} - {"user", "created_at", "updated_at"}
        changed = []
        for key, value in fields.items():
            if key in editable:
                setattr(settings_row, key, value)
                changed.append(key)
        if changed:
            settings_row.save(update_fields=changed + ["updated_at"])
        return settings_row

    @staticmethod
    def as_dict(user_id):
        row = UserSettings.objects.filter(user_id=user_id).first()
        if not row:
            return {}
        return {
            f.name: getattr(row, f.name)
            for f in UserSettings._meta.fields
            if f.name not in {"user", "created_at", "updated_at"}
        }
