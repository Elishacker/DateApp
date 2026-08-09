"""Serializers for the subscriptions REST surface."""
from rest_framework import serializers

from .models import Coupon, Plan, Subscription


class PlanSerializer(serializers.ModelSerializer):
    price_label = serializers.CharField(read_only=True)
    is_free = serializers.BooleanField(read_only=True)

    class Meta:
        model = Plan
        fields = ["id", "code", "name", "tagline", "description", "price",
                  "price_label", "currency", "duration_days", "trial_days",
                  "entitlements", "daily_likes", "daily_super_likes",
                  "daily_rewinds", "daily_messages", "monthly_boosts",
                  "is_free", "is_featured", "badge_color"]
        read_only_fields = fields


class SubscriptionSerializer(serializers.ModelSerializer):
    plan = PlanSerializer(read_only=True)
    days_remaining = serializers.IntegerField(read_only=True)
    is_live = serializers.BooleanField(read_only=True)

    class Meta:
        model = Subscription
        fields = ["id", "plan", "status", "started_at", "expires_at",
                  "trial_ends_at", "auto_renew", "renewal_count",
                  "boosts_remaining", "days_remaining", "is_live"]
        read_only_fields = fields


class StartSubscriptionSerializer(serializers.Serializer):
    plan_code = serializers.SlugField()
    provider = serializers.CharField(default="stripe")
    coupon_code = serializers.CharField(required=False, allow_blank=True, max_length=30)
    phone = serializers.CharField(
        required=False, allow_blank=True,
        help_text="Required for mobile-money providers.",
    )

    def validate_plan_code(self, value):
        if not Plan.objects.filter(code=value, is_active=True).exists():
            raise serializers.ValidationError("That plan is not available.")
        return value


class CouponQuoteSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=30)
    plan_code = serializers.SlugField()


class CouponSerializer(serializers.ModelSerializer):
    is_valid = serializers.BooleanField(read_only=True)

    class Meta:
        model = Coupon
        fields = ["code", "description", "discount_type", "value",
                  "valid_until", "is_valid"]
        read_only_fields = fields
