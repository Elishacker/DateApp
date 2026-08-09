"""Role policy — who holds which capability.

The capability *vocabulary* lives in :class:`apps.common.constants.Capability`
because every module needs to name one when guarding a view. The *policy* below
is owned by the accounts service and reached through its contract:

    services.accounts.has_capability(user_id, Capability.REVIEW_REPORTS)

Nothing in the platform should test ``user.is_staff`` or ``user.role == "admin"``
directly. A role check scatters policy across every view and template; a
capability is declared once here and enforced everywhere by one code path.
"""
from apps.common.constants import Capability

#: role -> capabilities. Nothing is inherited implicitly, so reading this table
#: tells you the whole truth about a role.
ROLE_CAPABILITIES = {
    "member": set(),

    "support": {
        Capability.HANDLE_SUPPORT,
        Capability.VIEW_MEMBER_DETAIL,
        Capability.REVIEW_REPORTS,
    },

    "analyst": {
        Capability.VIEW_ANALYTICS,
    },

    "moderator": {
        Capability.MODERATE_CONTENT,
        Capability.REVIEW_REPORTS,
        Capability.REVIEW_VERIFICATION,
        Capability.SHADOW_BAN,
        Capability.SUSPEND_USERS,
        Capability.VIEW_MEMBER_DETAIL,
        Capability.HANDLE_SUPPORT,
    },

    "admin": {
        Capability.MODERATE_CONTENT,
        Capability.REVIEW_REPORTS,
        Capability.REVIEW_VERIFICATION,
        Capability.SHADOW_BAN,
        Capability.SUSPEND_USERS,
        Capability.HANDLE_SUPPORT,
        Capability.VIEW_MEMBER_DETAIL,
        Capability.VIEW_ANALYTICS,
        Capability.VIEW_SECURITY_OPS,
        Capability.VIEW_AUDIT_TRAIL,
        Capability.MANAGE_USERS,
        Capability.MANAGE_PLANS,
        Capability.ISSUE_REFUNDS,
        Capability.ACCESS_DJANGO_ADMIN,
    },
}

#: Roles that see the staff area at all.
STAFF_ROLES = frozenset({"support", "analyst", "moderator", "admin"})

#: Staff navigation, declared beside the capability that gates each entry so a
#: new staff screen cannot be added without stating who may see it.
#: (url name, label, sprite icon name, required capability)
STAFF_NAVIGATION = (
    ("moderation:queue", "Moderation", "shield-check", Capability.MODERATE_CONTENT),
    ("reports:queue", "Reports", "flag-fill", Capability.REVIEW_REPORTS),
    ("verification:queue", "Verifications", "patch-check-fill", Capability.REVIEW_VERIFICATION),
    ("analytics:dashboard", "Analytics", "bar-chart-line-fill", Capability.VIEW_ANALYTICS),
    ("security:dashboard", "Security ops", "compass-fill", Capability.VIEW_SECURITY_OPS),
    ("audit:trail", "Audit trail", "journal-text", Capability.VIEW_AUDIT_TRAIL),
)


def capabilities_for(role, *, is_superuser=False):
    """Return the capability set for a role.

    A Django superuser gets everything — that is what superuser means, and
    pretending otherwise would only push people to bypass this module.
    """
    if is_superuser:
        return set(Capability)
    return set(ROLE_CAPABILITIES.get(role, set()))


def has_capability(role, capability, *, is_superuser=False):
    return capability in capabilities_for(role, is_superuser=is_superuser)


def is_staff_role(role, *, is_superuser=False):
    return is_superuser or role in STAFF_ROLES
