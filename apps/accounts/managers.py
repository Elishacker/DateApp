"""User manager — the only place a user row is created."""
from django.contrib.auth.base_user import BaseUserManager
from django.db import models
from django.utils import timezone


class UserQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True, status="active")

    def dateable(self):
        """Accounts that may appear in another member's feed."""
        return self.active().filter(has_completed_onboarding=True, is_email_verified=True)

    def searchable(self):
        """Accounts a name/username search may return.

        Deliberately looser than ``dateable()``: searching for someone by name
        is a targeted lookup, not passive browsing, so it doesn't carry the
        same fake-account exposure risk the swipe feed's email-verified gate
        guards against. Unverified members should still be findable by name.
        """
        return self.active().filter(has_completed_onboarding=True)

    def online(self):
        return self.filter(is_online=True)

    def recently_active(self, days=7):
        cutoff = timezone.now() - timezone.timedelta(days=days)
        return self.filter(last_active_at__gte=cutoff)

    def staff_members(self):
        return self.filter(models.Q(is_staff=True) | models.Q(role__in=["admin", "moderator", "support"]))


class UserManager(BaseUserManager):
    use_in_migrations = True

    def get_queryset(self):
        return UserQuerySet(self.model, using=self._db)

    def active(self):
        return self.get_queryset().active()

    def dateable(self):
        return self.get_queryset().dateable()

    def searchable(self):
        return self.get_queryset().searchable()

    def online(self):
        return self.get_queryset().online()

    def _create_user(self, email, username, password, **extra):
        if not email:
            raise ValueError("An email address is required.")
        if not username:
            raise ValueError("A username is required.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, username=username.lower(), **extra)
        user.set_password(password)
        user.password_changed_at = timezone.now()
        user.full_clean(exclude=["password"])
        user.save(using=self._db)
        return user

    def create_user(self, email, username, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, username, password, **extra)

    def create_superuser(self, email, username, password=None, **extra):
        extra.update(
            is_staff=True,
            is_superuser=True,
            is_active=True,
            status="active",
            role="admin",
            is_email_verified=True,
            has_completed_onboarding=True,
        )
        return self._create_user(email, username, password, **extra)
