"""Reusable DRF permission classes.

Staff gating is capability-based. Nothing here tests ``is_staff`` or a role name
directly — the policy lives in :mod:`apps.accounts.roles` and is reached through
the accounts contract, so changing who may do what is a one-line edit there.
"""
from rest_framework.permissions import SAFE_METHODS, BasePermission

from .registry import services


class IsOwner(BasePermission):
    """Object must expose ``user`` or ``owner`` matching the requester."""

    message = "You can only act on your own records."

    def has_object_permission(self, request, view, obj):
        owner = getattr(obj, "user", None) or getattr(obj, "owner", None)
        return owner == request.user


class IsOwnerOrReadOnly(IsOwner):
    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        return super().has_object_permission(request, view, obj)


class IsVerifiedUser(BasePermission):
    message = "Verify your email address to use this feature."

    def has_permission(self, request, view):
        return bool(request.user.is_authenticated and request.user.is_email_verified)


class IsOnboarded(BasePermission):
    message = "Finish setting up your profile first."

    def has_permission(self, request, view):
        return bool(request.user.is_authenticated and request.user.has_completed_onboarding)


class IsPremium(BasePermission):
    message = "This feature requires an active premium plan."

    def has_permission(self, request, view):
        return bool(
            request.user.is_authenticated
            and services.subscriptions.is_premium(str(request.user.id))
        )


class IsNotBanned(BasePermission):
    message = "This account is suspended."

    def has_permission(self, request, view):
        return not (request.user.is_authenticated and request.user.is_banned)


# ---------------------------------------------------------------------------
# Capability gating
# ---------------------------------------------------------------------------
class HasCapability(BasePermission):
    """Base class: subclass and set ``capability``.

    Prefer :func:`requires` for one-off use in a view.
    """

    capability = None
    message = "You do not have permission to perform this action."

    def has_permission(self, request, view):
        # A view may declare `required_capability` instead of subclassing.
        capability = self.capability or getattr(view, "required_capability", None)
        if capability is None:
            return False
        return bool(
            request.user.is_authenticated
            and services.accounts.has_capability(str(request.user.id), capability)
        )


def requires(capability, message=None):
    """Build a permission class for one capability.

        permission_classes = [IsAuthenticated, requires(Capability.REVIEW_REPORTS)]
    """
    return type(
        f"Requires_{capability}",
        (HasCapability,),
        {
            "capability": capability,
            "message": message or "You do not have permission to perform this action.",
        },
    )


class IsStaffMember(BasePermission):
    """Any staff role at all. Use a specific capability where you can."""

    message = "Staff access required."

    def has_permission(self, request, view):
        return bool(
            request.user.is_authenticated
            and services.accounts.is_staff_member(str(request.user.id))
        )


# ---- named shortcuts for the common gates ---------------------------------
def _capability(name):
    from apps.accounts.roles import Capability

    return getattr(Capability, name)


class IsModerator(HasCapability):
    """Kept for readability at call sites; backed by a capability."""

    message = "Moderator access required."

    def has_permission(self, request, view):
        self.capability = _capability("MODERATE_CONTENT")
        return super().has_permission(request, view)


class CanReviewReports(HasCapability):
    message = "You cannot review reports."

    def has_permission(self, request, view):
        self.capability = _capability("REVIEW_REPORTS")
        return super().has_permission(request, view)


class CanReviewVerification(HasCapability):
    message = "You cannot review verifications."

    def has_permission(self, request, view):
        self.capability = _capability("REVIEW_VERIFICATION")
        return super().has_permission(request, view)


class CanViewAnalytics(HasCapability):
    message = "Analytics access required."

    def has_permission(self, request, view):
        self.capability = _capability("VIEW_ANALYTICS")
        return super().has_permission(request, view)


class IsAdministrator(HasCapability):
    message = "Administrator access required."

    def has_permission(self, request, view):
        self.capability = _capability("MANAGE_USERS")
        return super().has_permission(request, view)
