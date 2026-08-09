"""Subscription lifecycle and entitlement resolution."""
import logging

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.common.events import Event, publish
from apps.common.exceptions import NotFound, ValidationError
from apps.common.services import CacheService

from .models import (
    Coupon,
    CouponRedemption,
    Entitlement,
    Plan,
    Subscription,
    SubscriptionStatus,
)

logger = logging.getLogger(__name__)

ENTITLEMENT_CACHE_SECONDS = 300


class PlanService:
    @staticmethod
    def default_plan():
        plan = Plan.objects.filter(is_default=True, is_active=True).first()
        if not plan:
            # Self-healing: a deployment must always have a free tier.
            plan, _ = Plan.objects.get_or_create(
                code="free",
                defaults={
                    "name": "Free", "tagline": "Get started", "price": 0,
                    "duration_days": 36500, "is_default": True, "sort_order": 0,
                    "entitlements": [], "daily_likes": 20, "daily_super_likes": 10,
                    "daily_rewinds": 0, "daily_messages": 200,
                },
            )
        return plan

    @staticmethod
    def get(code):
        plan = Plan.objects.filter(code=code, is_active=True).first()
        if not plan:
            raise NotFound("That plan is not available.")
        return plan

    @staticmethod
    def public_plans():
        """Render-ready plan cards for the pricing page."""
        rows = []
        for plan in Plan.objects.filter(is_active=True).order_by("sort_order", "price"):
            rows.append({
                "id": str(plan.id),
                "code": plan.code,
                "name": plan.name,
                "tagline": plan.tagline,
                "description": plan.description,
                "price": float(plan.price),
                "price_label": plan.price_label,
                "currency": plan.currency,
                "duration_days": plan.duration_days,
                "trial_days": plan.trial_days,
                "is_free": plan.is_free,
                "is_featured": plan.is_featured,
                "badge_color": plan.badge_color,
                "features": PlanService.feature_lines(plan),
            })
        return rows

    @staticmethod
    def feature_lines(plan):
        """Human bullet points — built here so the template just prints them."""
        lines = []
        lines.append("Unlimited likes" if plan.daily_likes is None
                     else f"{plan.daily_likes} likes a day")
        if plan.daily_super_likes:
            lines.append(f"{plan.daily_super_likes} super like"
                         f"{'s' if plan.daily_super_likes > 1 else ''} a day")
        if plan.daily_rewinds:
            lines.append(f"{plan.daily_rewinds} rewinds a day")
        lines.append("Unlimited messages" if plan.daily_messages is None
                     else f"{plan.daily_messages} messages a day")
        if plan.monthly_boosts:
            lines.append(f"{plan.monthly_boosts} boost"
                         f"{'es' if plan.monthly_boosts > 1 else ''} a month")

        labels = dict(Entitlement.choices)
        for entitlement in plan.entitlements or []:
            label = labels.get(entitlement)
            if label:
                lines.append(label)
        return lines


class SubscriptionService:
    @staticmethod
    def current(user_id):
        """The member's live subscription, or ``None`` if they are on free."""
        return Subscription.objects.filter(
            user_id=user_id,
            status__in=[SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING],
        ).filter(
            models_expiry_filter()
        ).select_related("plan").order_by("-started_at").first()

    @staticmethod
    def current_plan(user_id):
        subscription = SubscriptionService.current(user_id)
        return subscription.plan if subscription else PlanService.default_plan()

    @staticmethod
    def entitlements(user_id):
        cached = CacheService.get("subscriptions", "entitlements", user_id)
        if cached is not None:
            return cached
        plan = SubscriptionService.current_plan(user_id)
        values = list(plan.entitlements or [])
        CacheService.set("subscriptions", "entitlements", user_id,
                         value=values, ttl=ENTITLEMENT_CACHE_SECONDS)
        return values

    @staticmethod
    def has_entitlement(user_id, entitlement):
        return entitlement in SubscriptionService.entitlements(user_id)

    @staticmethod
    def invalidate(user_id):
        CacheService.delete("subscriptions", "entitlements", user_id)
        CacheService.delete("subscriptions", "limits", user_id)

    @staticmethod
    def quota_limits(user_id):
        cached = CacheService.get("subscriptions", "limits", user_id)
        if cached is not None:
            return cached
        limits = SubscriptionService.current_plan(user_id).quota_limits()
        CacheService.set("subscriptions", "limits", user_id,
                         value=limits, ttl=ENTITLEMENT_CACHE_SECONDS)
        return limits

    # ---- lifecycle ----------------------------------------------------------
    @staticmethod
    @transaction.atomic
    def start(user_id, plan_code, *, payment_id=None, coupon_code="",
              amount_paid=0, currency=None, with_trial=False):
        plan = PlanService.get(plan_code)

        # A member holds one live subscription at a time.
        Subscription.objects.filter(
            user_id=user_id,
            status__in=[SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING],
        ).update(status=SubscriptionStatus.CANCELLED, cancelled_at=timezone.now(),
                 cancel_reason="replaced by new plan")

        now = timezone.now()
        bonus_days = 0
        if coupon_code:
            bonus_days = CouponService.redeem(coupon_code, user_id, plan, amount_paid)

        trial_ends = now + timezone.timedelta(days=plan.trial_days) if (
            with_trial and plan.trial_days
        ) else None

        subscription = Subscription.objects.create(
            user_id=user_id, plan=plan,
            status=SubscriptionStatus.TRIALING if trial_ends else SubscriptionStatus.ACTIVE,
            started_at=now,
            expires_at=now + timezone.timedelta(days=plan.duration_days + bonus_days),
            trial_ends_at=trial_ends,
            payment_id=payment_id, coupon_code=coupon_code,
            amount_paid=amount_paid, currency=currency or plan.currency,
            boosts_remaining=plan.monthly_boosts,
        )

        SubscriptionService.invalidate(user_id)
        publish(Event.SUBSCRIPTION_STARTED, {
            "user_id": str(user_id),
            "subscription_id": str(subscription.id),
            "plan_code": plan.code,
            "plan_name": plan.name,
            "expires_at": subscription.expires_at.isoformat(),
            "amount": float(amount_paid),
        }, actor_id=user_id)
        logger.info("subscription %s started for %s", plan.code, user_id)
        return subscription

    @staticmethod
    @transaction.atomic
    def renew(subscription_id, payment_id=None):
        subscription = Subscription.objects.filter(id=subscription_id).select_related("plan").first()
        if not subscription:
            raise NotFound("Subscription not found.")

        base = max(subscription.expires_at or timezone.now(), timezone.now())
        subscription.expires_at = base + timezone.timedelta(days=subscription.plan.duration_days)
        subscription.status = SubscriptionStatus.ACTIVE
        subscription.renewal_count = F("renewal_count") + 1
        subscription.boosts_remaining = subscription.plan.monthly_boosts
        if payment_id:
            subscription.payment_id = payment_id
        subscription.save()

        SubscriptionService.invalidate(subscription.user_id)
        publish(Event.SUBSCRIPTION_RENEWED, {
            "user_id": str(subscription.user_id),
            "subscription_id": str(subscription.id),
            "plan_code": subscription.plan.code,
            "expires_at": subscription.expires_at.isoformat(),
        }, actor_id=subscription.user_id)
        return subscription

    @staticmethod
    def cancel(user_id, reason=""):
        subscription = SubscriptionService.current(user_id)
        if not subscription:
            raise ValidationError("You don't have an active subscription.")
        subscription.cancel(reason)
        SubscriptionService.invalidate(user_id)
        publish(Event.SUBSCRIPTION_CANCELLED, {
            "user_id": str(user_id),
            "subscription_id": str(subscription.id),
            "plan_code": subscription.plan.code,
            "access_until": subscription.expires_at.isoformat() if subscription.expires_at else None,
            "reason": reason,
        }, actor_id=user_id)
        return subscription

    @staticmethod
    def expire_due():
        """Called hourly by beat."""
        due = Subscription.objects.filter(
            status__in=[SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING,
                        SubscriptionStatus.CANCELLED],
            expires_at__lt=timezone.now(),
        ).select_related("plan")

        count = 0
        for subscription in due:
            subscription.expire()
            SubscriptionService.invalidate(subscription.user_id)
            publish(Event.SUBSCRIPTION_EXPIRED, {
                "user_id": str(subscription.user_id),
                "subscription_id": str(subscription.id),
                "plan_code": subscription.plan.code,
            }, actor_id=subscription.user_id)
            count += 1
        return count

    @staticmethod
    def consume_boost(user_id):
        subscription = SubscriptionService.current(user_id)
        if not subscription or subscription.boosts_remaining < 1:
            raise ValidationError("You have no boosts left.")
        subscription.boosts_remaining -= 1
        subscription.save(update_fields=["boosts_remaining", "updated_at"])
        return subscription.boosts_remaining

    @staticmethod
    def summary(user_id):
        """Render-ready subscription panel."""
        subscription = SubscriptionService.current(user_id)
        plan = subscription.plan if subscription else PlanService.default_plan()
        return {
            "plan_code": plan.code,
            "plan_name": plan.name,
            "price_label": plan.price_label,
            "is_free": plan.is_free,
            "is_premium": plan.is_premium,
            "status": subscription.status if subscription else "free",
            "status_label": (
                subscription.get_status_display() if subscription else "Free plan"
            ),
            "expires_at": (
                subscription.expires_at.isoformat()
                if subscription and subscription.expires_at else None
            ),
            "days_remaining": subscription.days_remaining if subscription else None,
            "auto_renew": subscription.auto_renew if subscription else False,
            "is_in_trial": subscription.is_in_trial if subscription else False,
            "boosts_remaining": subscription.boosts_remaining if subscription else 0,
            "features": PlanService.feature_lines(plan),
            "entitlements": list(plan.entitlements or []),
            "limits": plan.quota_limits(),
        }


class CouponService:
    @staticmethod
    def validate(code, user_id, plan=None):
        coupon = Coupon.objects.filter(code__iexact=(code or "").strip()).first()
        if not coupon or not coupon.is_valid:
            raise ValidationError("That coupon code is not valid.")
        if plan and coupon.applies_to_plans.exists():
            if not coupon.applies_to_plans.filter(pk=plan.pk).exists():
                raise ValidationError("That coupon does not apply to this plan.")
        used = CouponRedemption.objects.filter(coupon=coupon, user_id=user_id).count()
        if used >= coupon.per_user_limit:
            raise ValidationError("You have already used this coupon.")
        return coupon

    @staticmethod
    def quote(code, user_id, plan_code):
        """Preview the effect of a coupon without redeeming it."""
        plan = PlanService.get(plan_code)
        coupon = CouponService.validate(code, user_id, plan)
        new_amount, free_days = coupon.discount_for(plan.price)
        return {
            "code": coupon.code,
            "description": coupon.description,
            "original_amount": float(plan.price),
            "new_amount": float(new_amount),
            "saved": float(plan.price - new_amount),
            "free_days": free_days,
            "currency": plan.currency,
        }

    @staticmethod
    @transaction.atomic
    def redeem(code, user_id, plan, amount_paid):
        """Record the redemption; returns bonus days to add to the term."""
        coupon = CouponService.validate(code, user_id, plan)
        new_amount, free_days = coupon.discount_for(plan.price)

        CouponRedemption.objects.create(
            coupon=coupon, user_id=user_id, amount_saved=plan.price - new_amount
        )
        Coupon.objects.filter(pk=coupon.pk).update(
            redemption_count=F("redemption_count") + 1
        )
        return free_days


def models_expiry_filter():
    """Live subscriptions are those with no expiry or an expiry in the future."""
    from django.db.models import Q

    return Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
