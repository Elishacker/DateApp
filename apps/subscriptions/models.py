"""Plans, entitlements and member subscriptions.

``subscriptions`` is the single source of truth for *what a member is allowed to
do*. Every gate in the platform — swipe quotas, who-likes-you, advanced filters,
media messages — resolves here through ``has_entitlement``. Payments never
grants access directly; it publishes ``PAYMENT_SUCCEEDED`` and this module
decides what that buys.
"""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.constants import Currency
from apps.common.models import ServiceReference, TimeStampedModel


class Entitlement(models.TextChoices):
    """The complete vocabulary of paid capabilities."""

    UNLIMITED_LIKES = "unlimited_likes", "Unlimited likes"
    SEE_WHO_LIKES_YOU = "see_who_likes_you", "See who likes you"
    SEE_PROFILE_VIEWERS = "see_profile_viewers", "See profile viewers"
    ADVANCED_FILTERS = "advanced_filters", "Advanced filters"
    REWIND = "rewind", "Rewind last swipe"
    BOOST = "boost", "Profile boost"
    MEDIA_MESSAGES = "media_messages", "Photos and voice notes in chat"
    UNLIMITED_MESSAGES = "unlimited_messages", "Unlimited messages"
    INCOGNITO = "incognito", "Browse invisibly"
    PRIORITY_SUPPORT = "priority_support", "Priority support"
    READ_RECEIPTS = "read_receipts", "Read receipts"
    NO_ADS = "no_ads", "No advertising"


class Plan(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.SlugField(max_length=30, unique=True)
    name = models.CharField(max_length=60)
    tagline = models.CharField(max_length=140, blank=True)
    description = models.TextField(blank=True)

    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.TZS)
    duration_days = models.PositiveSmallIntegerField(default=30)
    trial_days = models.PositiveSmallIntegerField(default=0)

    entitlements = models.JSONField(
        default=list, blank=True, help_text="List of Entitlement values."
    )

    #: ``None`` means unlimited.
    daily_likes = models.PositiveSmallIntegerField(null=True, blank=True, default=20)
    daily_super_likes = models.PositiveSmallIntegerField(null=True, blank=True, default=1)
    daily_rewinds = models.PositiveSmallIntegerField(null=True, blank=True, default=0)
    daily_messages = models.PositiveSmallIntegerField(null=True, blank=True, default=50)
    monthly_boosts = models.PositiveSmallIntegerField(default=0)

    is_active = models.BooleanField(default=True, db_index=True)
    is_default = models.BooleanField(
        default=False, help_text="The plan every new member starts on."
    )
    is_featured = models.BooleanField(default=False)
    sort_order = models.PositiveSmallIntegerField(default=0)
    badge_color = models.CharField(max_length=20, blank=True)

    class Meta:
        db_table = "subscriptions_plan"
        ordering = ["sort_order", "price"]

    def __str__(self):
        return self.name

    @property
    def is_free(self):
        return self.price == 0

    @property
    def is_premium(self):
        return not self.is_free

    @property
    def price_label(self):
        if self.is_free:
            return "Free"
        return f"{self.currency} {self.price:,.0f}"

    def has(self, entitlement):
        return entitlement in (self.entitlements or [])

    def quota_limits(self):
        return {
            "daily_likes": self.daily_likes,
            "daily_super_likes": self.daily_super_likes,
            "daily_rewinds": self.daily_rewinds,
            "daily_messages": self.daily_messages,
            "monthly_boosts": self.monthly_boosts,
        }


class SubscriptionStatus(models.TextChoices):
    TRIALING = "trialing", "In trial"
    ACTIVE = "active", "Active"
    PAST_DUE = "past_due", "Past due"
    CANCELLED = "cancelled", "Cancelled"
    EXPIRED = "expired", "Expired"


class Subscription(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="subscriptions"
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")

    status = models.CharField(
        max_length=12, choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.ACTIVE, db_index=True,
    )
    started_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=200, blank=True)

    auto_renew = models.BooleanField(default=True)
    renewal_count = models.PositiveSmallIntegerField(default=0)

    # The payment that started this subscription lives in another service.
    payment_id = ServiceReference("payments", null=True, blank=True)
    coupon_code = models.CharField(max_length=30, blank=True)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.TZS)

    boosts_remaining = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "subscriptions_subscription"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["status", "expires_at"]),
        ]

    def __str__(self):
        return f"{self.user_id} on {self.plan_id} ({self.status})"

    @property
    def is_live(self):
        if self.status not in {SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING}:
            return False
        return self.expires_at is None or self.expires_at > timezone.now()

    @property
    def days_remaining(self):
        if not self.expires_at:
            return None
        delta = self.expires_at - timezone.now()
        return max(delta.days, 0)

    @property
    def is_in_trial(self):
        return bool(self.trial_ends_at and self.trial_ends_at > timezone.now())

    def expire(self):
        self.status = SubscriptionStatus.EXPIRED
        self.save(update_fields=["status", "updated_at"])
        return self

    def cancel(self, reason=""):
        self.status = SubscriptionStatus.CANCELLED
        self.auto_renew = False
        self.cancelled_at = timezone.now()
        self.cancel_reason = reason[:200]
        self.save(update_fields=["status", "auto_renew", "cancelled_at",
                                 "cancel_reason", "updated_at"])
        return self


class Coupon(TimeStampedModel):
    class DiscountType(models.TextChoices):
        PERCENT = "percent", "Percentage off"
        FIXED = "fixed", "Fixed amount off"
        FREE_DAYS = "free_days", "Free days"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=30, unique=True, db_index=True)
    description = models.CharField(max_length=200, blank=True)
    discount_type = models.CharField(
        max_length=12, choices=DiscountType.choices, default=DiscountType.PERCENT
    )
    value = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    applies_to_plans = models.ManyToManyField(Plan, blank=True, related_name="coupons")
    max_redemptions = models.PositiveIntegerField(null=True, blank=True)
    redemption_count = models.PositiveIntegerField(default=0)
    per_user_limit = models.PositiveSmallIntegerField(default=1)

    valid_from = models.DateTimeField(default=timezone.now)
    valid_until = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "subscriptions_coupon"
        ordering = ["-created_at"]

    def __str__(self):
        return self.code

    @property
    def is_valid(self):
        if not self.is_active:
            return False
        now = timezone.now()
        if self.valid_from > now:
            return False
        if self.valid_until and self.valid_until < now:
            return False
        if self.max_redemptions and self.redemption_count >= self.max_redemptions:
            return False
        return True

    def discount_for(self, amount):
        """Return ``(discounted_amount, extra_free_days)``."""
        if self.discount_type == self.DiscountType.PERCENT:
            return max(amount - (amount * self.value / 100), 0), 0
        if self.discount_type == self.DiscountType.FIXED:
            return max(amount - self.value, 0), 0
        return amount, int(self.value)


class CouponRedemption(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    coupon = models.ForeignKey(Coupon, on_delete=models.CASCADE, related_name="redemptions")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="coupon_redemptions"
    )
    subscription = models.ForeignKey(
        Subscription, on_delete=models.SET_NULL, null=True, blank=True, related_name="redemptions"
    )
    amount_saved = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        db_table = "subscriptions_coupon_redemption"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.coupon_id} by {self.user_id}"
