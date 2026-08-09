"""Platform-wide enumerations.

Choice sets referenced by more than one module live here so modules never import
each other just to read a label.
"""
from django.db import models


class Gender(models.TextChoices):
    WOMAN = "woman", "Woman"
    MAN = "man", "Man"
    NON_BINARY = "non_binary", "Non-binary"
    OTHER = "other", "Other"
    PREFER_NOT = "prefer_not", "Prefer not to say"


class RelationshipGoal(models.TextChoices):
    LONG_TERM = "long_term", "Long-term relationship"
    SHORT_TERM = "short_term", "Something casual"
    FRIENDSHIP = "friendship", "New friends"
    MARRIAGE = "marriage", "Marriage"
    UNSURE = "unsure", "Still figuring it out"


class LifestyleChoice(models.TextChoices):
    NEVER = "never", "Never"
    SOCIALLY = "socially", "Socially"
    REGULARLY = "regularly", "Regularly"
    PREFER_NOT = "prefer_not", "Prefer not to say"


class ChildrenStatus(models.TextChoices):
    NONE = "none", "Don't have children"
    HAVE = "have", "Have children"
    WANT = "want", "Want children"
    DONT_WANT = "dont_want", "Don't want children"
    OPEN = "open", "Open to children"


class EducationLevel(models.TextChoices):
    HIGH_SCHOOL = "high_school", "High school"
    CERTIFICATE = "certificate", "Certificate"
    DIPLOMA = "diploma", "Diploma"
    BACHELOR = "bachelor", "Bachelor's degree"
    MASTER = "master", "Master's degree"
    DOCTORATE = "doctorate", "Doctorate"
    OTHER = "other", "Other"


class VerificationLevel(models.IntegerChoices):
    NONE = 0, "Unverified"
    EMAIL = 1, "Email verified"
    PHONE = 2, "Phone verified"
    PHOTO = 3, "Photo verified"
    IDENTITY = 4, "Identity verified"


class Capability(models.TextChoices):
    """The vocabulary of privileged actions.

    Lives in the shared kernel because every module needs to *name* a capability
    when guarding a view. Which role actually holds which capability is policy,
    and that belongs to the accounts service (``apps.accounts.roles``).
    """

    # Trust and safety
    MODERATE_CONTENT = "moderate_content", "Review the moderation queue"
    REVIEW_REPORTS = "review_reports", "Review and resolve abuse reports"
    REVIEW_VERIFICATION = "review_verification", "Approve or reject verifications"
    SHADOW_BAN = "shadow_ban", "Shadow ban members"
    SUSPEND_USERS = "suspend_users", "Suspend or ban accounts"

    # Support
    HANDLE_SUPPORT = "handle_support", "Answer support tickets"
    VIEW_MEMBER_DETAIL = "view_member_detail", "See a member's account detail"

    # Insight
    VIEW_ANALYTICS = "view_analytics", "See the analytics dashboard"
    VIEW_SECURITY_OPS = "view_security_ops", "See the security operations console"
    VIEW_AUDIT_TRAIL = "view_audit_trail", "Read the platform audit trail"

    # Administration
    MANAGE_USERS = "manage_users", "Change roles and account state"
    MANAGE_PLANS = "manage_plans", "Create and edit subscription plans"
    ISSUE_REFUNDS = "issue_refunds", "Issue payment refunds"
    ACCESS_DJANGO_ADMIN = "access_django_admin", "Open the Django admin"


class Currency(models.TextChoices):
    TZS = "TZS", "Tanzanian Shilling"
    KES = "KES", "Kenyan Shilling"
    UGX = "UGX", "Ugandan Shilling"
    USD = "USD", "US Dollar"
    EUR = "EUR", "Euro"


EARTH_RADIUS_KM = 6371.0

#: Interest catalogue seeded on first run and offered during onboarding.
DEFAULT_INTERESTS = [
    ("Travel", "lifestyle"), ("Music", "arts"), ("Movies", "arts"),
    ("Fitness", "sport"), ("Football", "sport"), ("Basketball", "sport"),
    ("Cooking", "lifestyle"), ("Reading", "arts"), ("Photography", "arts"),
    ("Technology", "career"), ("Startups", "career"), ("Cybersecurity", "career"),
    ("Gaming", "leisure"), ("Hiking", "outdoors"), ("Beach", "outdoors"),
    ("Coffee", "lifestyle"), ("Dancing", "arts"), ("Fashion", "lifestyle"),
    ("Volunteering", "values"), ("Faith", "values"), ("Politics", "values"),
    ("Pets", "lifestyle"), ("Yoga", "wellness"), ("Meditation", "wellness"),
    ("Art", "arts"), ("Podcasts", "leisure"), ("Languages", "learning"),
    ("Entrepreneurship", "career"), ("Investing", "career"), ("Nature", "outdoors"),
]
