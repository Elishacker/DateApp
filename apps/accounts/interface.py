"""Public contract of the accounts service.

The ONLY module-level symbol other services may import is ``service``.
Every method here is wire-safe: primitives and plain dicts in, primitives and
plain dicts out — no ORM objects cross this line.
"""
from apps.common.interface import ModuleInterface, UserRef

from apps.common.constants import Capability

from .models import AccountStatus, Device, User
from .roles import (
    ROLE_CAPABILITIES,
    STAFF_NAVIGATION,
    capabilities_for,
    is_staff_role,
)
from .services import AccountService, DeviceService, SettingsService


class AccountsInterface(ModuleInterface):
    name = "accounts"
    depends_on = ()  # identity is the root of the graph: it calls nobody

    # ---- reads --------------------------------------------------------------
    def get_user_ref(self, user_id):
        """Minimal cross-module representation of a person, or ``None``."""
        user = User.objects.filter(id=user_id).first()
        return self._to_ref(user).to_dict() if user else None

    def get_user_refs(self, user_ids):
        """Bulk variant — one query, keyed by id. Use this in list views."""
        users = User.objects.filter(id__in=list(user_ids))
        return {str(u.id): self._to_ref(u).to_dict() for u in users}

    def exists(self, user_id):
        return User.objects.filter(id=user_id).exists()

    def is_active_member(self, user_id):
        return User.objects.filter(
            id=user_id, is_active=True, status=AccountStatus.ACTIVE
        ).exists()

    def get_account_state(self, user_id):
        user = User.objects.filter(id=user_id).first()
        if not user:
            return None
        return {
            "id": str(user.id),
            "email": user.email,
            "phone": user.phone,
            "username": user.username,
            "status": user.status,
            "role": user.role,
            "is_active": user.is_active,
            "is_banned": user.is_banned,
            "is_locked": user.is_locked,
            "is_email_verified": user.is_email_verified,
            "is_phone_verified": user.is_phone_verified,
            "verification_level": user.verification_level,
            "has_completed_onboarding": user.has_completed_onboarding,
            "onboarding_step": user.onboarding_step,
            "date_joined": user.date_joined.isoformat(),
            "last_active_at": user.last_active_at.isoformat() if user.last_active_at else None,
        }

    def get_notification_settings(self, user_id):
        return SettingsService.as_dict(user_id)

    def get_privacy_settings(self, user_id):
        data = SettingsService.as_dict(user_id)
        return {k: v for k, v in data.items()
                if k.startswith("show_") or k in {"incognito_mode", "read_receipts_enabled"}}

    def list_dateable_ids(self, exclude_ids=(), limit=500):
        """Candidate pool for discovery — ids only, so no profile data leaks."""
        return [
            str(pk) for pk in User.objects.dateable()
            .exclude(id__in=list(exclude_ids))
            .values_list("id", flat=True)[:limit]
        ]

    def search_ids(self, query, exclude_ids=(), limit=200):
        """Match a free-text query against the fields accounts owns: the
        member's name and username. Profile fields are searched separately by
        the profiles service — neither module reads the other's tables."""
        from django.db.models import Q

        query = (query or "").strip()
        if len(query) < 2:
            return []
        return [
            str(pk) for pk in User.objects.searchable()
            .filter(
                Q(first_name__icontains=query)
                | Q(last_name__icontains=query)
                | Q(username__icontains=query)
            )
            .exclude(id__in=list(exclude_ids))
            .values_list("id", flat=True)[:limit]
        ]

    def list_recently_joined_ids(self, exclude_ids=(), limit=120, days=14):
        from django.utils import timezone

        cutoff = timezone.now() - timezone.timedelta(days=days)
        return [
            str(pk) for pk in User.objects.dateable()
            .filter(date_joined__gte=cutoff)
            .exclude(id__in=list(exclude_ids))
            .order_by("-date_joined")
            .values_list("id", flat=True)[:limit]
        ]

    def list_online_ids(self, exclude_ids=(), limit=120):
        return [
            str(pk) for pk in User.objects.dateable()
            .filter(is_online=True)
            .exclude(id__in=list(exclude_ids))
            .values_list("id", flat=True)[:limit]
        ]

    def get_push_tokens(self, user_id):
        return DeviceService.push_tokens_for(user_id)

    def get_contact_channels(self, user_id):
        user = User.objects.filter(id=user_id).only("email", "phone", "first_name", "username").first()
        if not user:
            return {}
        return {
            "email": user.email,
            "phone": user.phone or "",
            "name": user.first_name or user.username,
        }

    # ---- roles and capabilities --------------------------------------------
    def get_capabilities(self, user_id):
        """Every capability this account holds. The basis of all staff gating."""
        user = User.objects.filter(id=user_id).only("role", "is_superuser").first()
        if not user:
            return []
        return sorted(capabilities_for(user.role, is_superuser=user.is_superuser))

    def has_capability(self, user_id, capability):
        user = User.objects.filter(id=user_id).only("role", "is_superuser").first()
        if not user:
            return False
        return capability in capabilities_for(user.role, is_superuser=user.is_superuser)

    def is_staff_member(self, user_id):
        user = User.objects.filter(id=user_id).only("role", "is_superuser").first()
        return bool(user and is_staff_role(user.role, is_superuser=user.is_superuser))

    def get_role(self, user_id):
        user = User.objects.filter(id=user_id).only("role", "is_superuser", "is_staff").first()
        if not user:
            return None
        return {
            "role": user.role,
            "label": user.get_role_display(),
            "is_superuser": user.is_superuser,
            "is_staff_area": is_staff_role(user.role, is_superuser=user.is_superuser),
            "capabilities": sorted(
                capabilities_for(user.role, is_superuser=user.is_superuser)
            ),
        }

    def set_role(self, user_id, role, *, actor_id=None):
        """Change a member's role. Also syncs Django's ``is_staff`` flag."""
        if role not in ROLE_CAPABILITIES:
            raise ValueError(f"Unknown role '{role}'.")

        user = User.objects.filter(id=user_id).first()
        if not user:
            return None

        previous = user.role
        user.role = role
        # Keep is_staff aligned so the Django admin gate matches our roles.
        user.is_staff = Capability.ACCESS_DJANGO_ADMIN in capabilities_for(role)
        user.save(update_fields=["role", "is_staff"])

        from apps.common.events import Event, publish

        # Privilege changes are exactly the kind of thing an audit trail exists
        # for, so this is deliberately not optional.
        publish(Event.ROLE_CHANGED, {
            "user_id": str(user.id),
            "target_user_id": str(user.id),
            "previous_role": previous,
            "role": role,
        }, actor_id=actor_id or user_id)
        return self.get_role(user_id)

    def get_staff_navigation(self, user_id):
        """Render-ready staff nav for this account — empty for ordinary members.

        Built here rather than in a template so the sidebar contains no role
        logic at all, and so a screen cannot be added without declaring the
        capability that guards it.
        """
        user = User.objects.filter(id=user_id).only("role", "is_superuser").first()
        if not user or not is_staff_role(user.role, is_superuser=user.is_superuser):
            return []

        held = capabilities_for(user.role, is_superuser=user.is_superuser)
        return [
            {"url_name": url_name, "label": label, "icon": icon}
            for url_name, label, icon, capability in STAFF_NAVIGATION
            if capability in held
        ]

    def list_staff(self):
        from .roles import STAFF_ROLES

        rows = User.objects.filter(role__in=STAFF_ROLES).only(
            "id", "email", "username", "role", "is_superuser"
        )
        return [
            {"id": str(u.id), "email": u.email, "username": u.username,
             "role": u.role, "label": u.get_role_display(),
             "is_superuser": u.is_superuser}
            for u in rows
        ]

    def count_devices(self, user_id):
        return Device.objects.filter(user_id=user_id, revoked_at__isnull=True).count()

    def prune_revoked_devices(self, days=90):
        """Maintenance hook called by the security service's sweep."""
        from django.utils import timezone

        cutoff = timezone.now() - timezone.timedelta(days=days)
        deleted, _ = Device.objects.filter(revoked_at__lt=cutoff).delete()
        return deleted

    # ---- writes -------------------------------------------------------------
    def create_account(self, *, email, username, password, first_name="",
                       date_of_birth=None, phone=None, accepted_terms=False,
                       marketing_opt_in=False):
        """Create an identity. Returns the new account state as a dict."""
        user = AccountService.create_account(
            email=email, username=username, password=password,
            first_name=first_name, date_of_birth=date_of_birth, phone=phone,
            accepted_terms=accepted_terms, marketing_opt_in=marketing_opt_in,
        )
        return self.get_account_state(user.id)

    def activate(self, user_id):
        user = AccountService.activate(user_id)
        return {"user_id": str(user.id), "status": user.status}

    def deactivate(self, user_id, reason=""):
        user = AccountService.deactivate(user_id, reason)
        return {"user_id": str(user.id), "status": user.status}

    def set_verification_flag(self, user_id, flag, value=True):
        user = AccountService.set_verification_flag(user_id, flag, value)
        return {"user_id": str(user.id), "verification_level": user.verification_level}

    def mark_onboarding_complete(self, user_id, step=None):
        updates = {"has_completed_onboarding": True}
        if step is not None:
            updates["onboarding_step"] = step
        User.objects.filter(id=user_id).update(**updates)
        return True

    def set_onboarding_step(self, user_id, step):
        User.objects.filter(id=user_id).update(onboarding_step=step)
        return True

    def update_avatar_projection(self, user_id, avatar_url):
        AccountService.update_avatar_projection(user_id, avatar_url)
        return True

    def suspend(self, user_id, reason="", permanent=False, actor_id=None):
        user = AccountService.ban(user_id, reason=reason, permanent=permanent, actor_id=actor_id)
        return {"user_id": str(user.id), "status": user.status}

    def set_online(self, user_id, online=True):
        user = User.objects.filter(id=user_id).first()
        if user:
            user.mark_online(online)
        return bool(user)

    def register_device(self, user_id, fingerprint, user_agent="", ip=None):
        user = User.objects.filter(id=user_id).first()
        if not user:
            return None
        device = DeviceService.register(
            user, fingerprint=fingerprint, user_agent=user_agent, ip=ip
        )
        if not device:
            return None
        return {
            "id": str(device.id),
            "is_trusted": device.is_trusted,
            "platform": device.platform,
            "name": device.name,
            "created": device.last_seen_at == device.created_at,
        }

    # ---- helpers ------------------------------------------------------------
    @staticmethod
    def _to_ref(user):
        return UserRef(
            id=str(user.id),
            username=user.username,
            display_name=user.display_name,
            avatar_url=user.avatar_url,
            age=user.age,
            is_verified=user.is_verified,
            is_online=user.is_online,
        )


service = AccountsInterface()
