from django.contrib import admin

from .models import Like, SwipeQuota


@admin.register(Like)
class LikeAdmin(admin.ModelAdmin):
    list_display = ("sender", "receiver", "kind", "score_at_swipe",
                    "seen_by_receiver", "is_rewound", "created_at")
    list_filter = ("kind", "is_rewound", "seen_by_receiver", "source")
    search_fields = ("sender__email", "receiver__email")
    date_hierarchy = "created_at"
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(SwipeQuota)
class SwipeQuotaAdmin(admin.ModelAdmin):
    list_display = ("user", "likes_used", "super_likes_used", "rewinds_used", "reset_at")
    search_fields = ("user__email",)
    actions = ["reset_quotas"]

    @admin.action(description="Reset selected quotas")
    def reset_quotas(self, request, queryset):
        for quota in queryset:
            quota.reset()
        self.message_user(request, f"{queryset.count()} quota(s) reset.")
