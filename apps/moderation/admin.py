from django.contrib import admin
from django.utils.html import format_html

from .models import BannedTerm, ModerationCase, TrustScore


@admin.register(ModerationCase)
class ModerationCaseAdmin(admin.ModelAdmin):
    list_display = ("object_type", "owner_id", "status", "severity",
                    "risk_score", "preview", "created_at")
    list_filter = ("status", "object_type", "severity")
    search_fields = ("owner_id", "object_id")
    date_hierarchy = "created_at"
    readonly_fields = ("id", "preview", "created_at", "updated_at")
    actions = ["approve_cases", "reject_cases"]

    @admin.display(description="Content")
    def preview(self, obj):
        if obj.content_url:
            return format_html('<img src="{}" style="height:60px;border-radius:6px">',
                               obj.content_url)
        return (obj.content_snapshot[:60] + "…") if obj.content_snapshot else "—"

    @admin.action(description="Approve selected content")
    def approve_cases(self, request, queryset):
        from .services import ModerationService

        for case in queryset.filter(status="pending"):
            ModerationService.decide(case, True, request.user, "Approved in admin")
        self.message_user(request, "Selected content approved.")

    @admin.action(description="Reject selected content")
    def reject_cases(self, request, queryset):
        from .services import ModerationService

        for case in queryset.filter(status="pending"):
            ModerationService.decide(case, False, request.user, "Rejected in admin")
        self.message_user(request, "Selected content rejected.")


@admin.register(BannedTerm)
class BannedTermAdmin(admin.ModelAdmin):
    list_display = ("term", "category", "action", "severity", "is_regex",
                    "hit_count", "is_active")
    list_filter = ("category", "action", "severity", "is_active", "is_regex")
    search_fields = ("term",)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # The screening service caches the term list; drop it on any edit.
        from apps.common.services import CacheService

        CacheService.delete("moderation", "terms")


@admin.register(TrustScore)
class TrustScoreAdmin(admin.ModelAdmin):
    list_display = ("user", "score", "band", "reports_received",
                    "content_rejected", "is_shadow_banned")
    list_filter = ("is_shadow_banned",)
    search_fields = ("user__email",)
    readonly_fields = ("band",)
