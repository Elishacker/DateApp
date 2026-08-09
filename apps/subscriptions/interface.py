"""Public contract of the subscriptions service.

Every paywall in Zynora goes through ``has_entitlement``. Nothing else in the
platform is allowed to reason about plans.
"""
from apps.common.interface import ModuleInterface

from .models import Entitlement, Subscription, SubscriptionStatus
from .services import CouponService, PlanService, SubscriptionService


class SubscriptionsInterface(ModuleInterface):
    name = "subscriptions"
    depends_on = ()  # entitlements must resolve without calling anyone

    # ---- gating -------------------------------------------------------------
    def has_entitlement(self, user_id, entitlement):
        return SubscriptionService.has_entitlement(user_id, entitlement)

    def get_entitlements(self, user_id):
        return SubscriptionService.entitlements(user_id)

    def get_quota_limits(self, user_id):
        return SubscriptionService.quota_limits(user_id)

    def can_send_message(self, user_id, conversation_id=None):
        """Daily message ceiling. Unlimited plans short-circuit."""
        limits = SubscriptionService.quota_limits(user_id)
        if limits["daily_messages"] is None:
            return True

        from django.utils import timezone

        from apps.common.services import CacheService

        key_parts = ("messages", user_id, timezone.now().date().isoformat())
        used = CacheService.get(*key_parts, default=0)
        if used >= limits["daily_messages"]:
            return False
        CacheService.set(*key_parts, value=used + 1, ttl=86400)
        return True

    def is_premium(self, user_id):
        return SubscriptionService.current_plan(user_id).is_premium

    # ---- reads --------------------------------------------------------------
    def get_current_plan(self, user_id):
        plan = SubscriptionService.current_plan(user_id)
        return {
            "code": plan.code, "name": plan.name, "price_label": plan.price_label,
            "is_free": plan.is_free, "is_premium": plan.is_premium,
            "entitlements": list(plan.entitlements or []), "limits": plan.quota_limits(),
        }

    def get_summary(self, user_id):
        return SubscriptionService.summary(user_id)

    def list_public_plans(self):
        return PlanService.public_plans()

    def get_subscription(self, user_id):
        subscription = SubscriptionService.current(user_id)
        if not subscription:
            return None
        return {
            "id": str(subscription.id),
            "plan_code": subscription.plan.code,
            "status": subscription.status,
            "started_at": subscription.started_at.isoformat(),
            "expires_at": (
                subscription.expires_at.isoformat() if subscription.expires_at else None
            ),
            "auto_renew": subscription.auto_renew,
            "days_remaining": subscription.days_remaining,
        }

    # ---- writes -------------------------------------------------------------
    def start_subscription(self, user_id, plan_code, *, payment_id=None,
                           coupon_code="", amount_paid=0, currency=None, with_trial=False):
        subscription = SubscriptionService.start(
            user_id, plan_code, payment_id=payment_id, coupon_code=coupon_code,
            amount_paid=amount_paid, currency=currency, with_trial=with_trial,
        )
        return {"id": str(subscription.id), "plan_code": subscription.plan.code,
                "expires_at": subscription.expires_at.isoformat()}

    def renew_subscription(self, subscription_id, payment_id=None):
        subscription = SubscriptionService.renew(subscription_id, payment_id)
        return {"id": str(subscription.id),
                "expires_at": subscription.expires_at.isoformat()}

    def cancel_subscription(self, user_id, reason=""):
        subscription = SubscriptionService.cancel(user_id, reason)
        return {"id": str(subscription.id), "status": subscription.status}

    def consume_boost(self, user_id):
        return SubscriptionService.consume_boost(user_id)

    def invalidate(self, user_id):
        SubscriptionService.invalidate(user_id)
        return True

    def quote_coupon(self, code, user_id, plan_code):
        return CouponService.quote(code, user_id, plan_code)

    # ---- analytics ----------------------------------------------------------
    def revenue_stats(self, since=None):
        from django.db.models import Count, Sum

        qs = Subscription.objects.all()
        if since:
            qs = qs.filter(started_at__gte=since)
        aggregate = qs.aggregate(revenue=Sum("amount_paid"), count=Count("id"))
        return {
            "revenue": float(aggregate["revenue"] or 0),
            "subscriptions": aggregate["count"] or 0,
            "active": Subscription.objects.filter(status=SubscriptionStatus.ACTIVE).count(),
            "by_plan": list(
                qs.values("plan__code").annotate(count=Count("id"), revenue=Sum("amount_paid"))
            ),
        }

    @property
    def entitlement_choices(self):
        return list(Entitlement.values)


service = SubscriptionsInterface()
