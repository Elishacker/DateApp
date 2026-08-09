from django.contrib import admin

from .models import Coupon, CouponRedemption, Plan, Subscription


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "price_label", "duration_days",
                    "is_active", "is_default", "is_featured", "sort_order")
    list_filter = ("is_active", "is_default", "is_featured", "currency")
    search_fields = ("name", "code")
    prepopulated_fields = {"code": ("name",)}

    fieldsets = (
        (None, {"fields": ("code", "name", "tagline", "description")}),
        ("Pricing", {"fields": ("price", "currency", "duration_days", "trial_days")}),
        ("Entitlements", {"fields": ("entitlements",)}),
        ("Quotas", {"fields": ("daily_likes", "daily_super_likes", "daily_rewinds",
                               "daily_messages", "monthly_boosts"),
                    "description": "Leave blank for unlimited."}),
        ("Display", {"fields": ("is_active", "is_default", "is_featured",
                                "sort_order", "badge_color")}),
    )


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("user", "plan", "status", "started_at", "expires_at",
                    "days_remaining", "auto_renew", "amount_paid")
    list_filter = ("status", "plan", "auto_renew")
    search_fields = ("user__email", "coupon_code")
    date_hierarchy = "started_at"
    readonly_fields = ("id", "payment_id", "renewal_count", "created_at", "updated_at")
    actions = ["expire_subscriptions"]

    @admin.action(description="Expire selected subscriptions")
    def expire_subscriptions(self, request, queryset):
        for subscription in queryset:
            subscription.expire()
        self.message_user(request, f"{queryset.count()} subscription(s) expired.")


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = ("code", "discount_type", "value", "redemption_count",
                    "max_redemptions", "valid_until", "is_active")
    list_filter = ("discount_type", "is_active")
    search_fields = ("code", "description")
    filter_horizontal = ("applies_to_plans",)


@admin.register(CouponRedemption)
class CouponRedemptionAdmin(admin.ModelAdmin):
    list_display = ("coupon", "user", "amount_saved", "created_at")
    search_fields = ("coupon__code", "user__email")
    date_hierarchy = "created_at"
