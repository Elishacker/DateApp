from django.contrib import admin
from django.utils.html import format_html

from .models import VerificationBadge, VerificationRequest


@admin.register(VerificationRequest)
class VerificationRequestAdmin(admin.ModelAdmin):
    list_display = ("user", "kind", "status", "challenge_pose",
                    "preview", "created_at", "reviewed_at")
    list_filter = ("kind", "status")
    search_fields = ("user__email", "target_value")
    date_hierarchy = "created_at"
    readonly_fields = ("id", "preview", "created_at", "updated_at")
    actions = ["approve_selected", "reject_selected"]

    @admin.display(description="Evidence")
    def preview(self, obj):
        if obj.document:
            return format_html('<img src="{}" style="height:80px;border-radius:6px">',
                               obj.document.url)
        return "— (purged after review)"

    @admin.action(description="Approve selected verifications")
    def approve_selected(self, request, queryset):
        from .services import VerificationService

        count = 0
        for item in queryset.filter(status="pending"):
            VerificationService.approve(item, request.user)
            count += 1
        self.message_user(request, f"{count} verification(s) approved.")

    @admin.action(description="Reject selected verifications")
    def reject_selected(self, request, queryset):
        from .services import VerificationService

        count = 0
        for item in queryset.filter(status="pending"):
            VerificationService.reject(item, "Rejected in admin", request.user)
            count += 1
        self.message_user(request, f"{count} verification(s) rejected.")


@admin.register(VerificationBadge)
class VerificationBadgeAdmin(admin.ModelAdmin):
    list_display = ("user", "label", "level", "email_verified_at",
                    "phone_verified_at", "selfie_verified_at", "identity_verified_at")
    search_fields = ("user__email",)
    readonly_fields = ("user", "level", "label")
