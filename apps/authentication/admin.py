from django.contrib import admin
from django.utils.html import format_html

from .models import ActiveSession, LoginAttempt, MFASecret, SecurityToken, SocialAccount


@admin.register(SecurityToken)
class SecurityTokenAdmin(admin.ModelAdmin):
    list_display = ("user", "purpose", "created_at", "expires_at", "used_at", "attempts")
    list_filter = ("purpose",)
    search_fields = ("user__email",)
    readonly_fields = ("id", "token_hash", "created_at")


@admin.register(LoginAttempt)
class LoginAttemptAdmin(admin.ModelAdmin):
    list_display = ("created_at", "identifier", "outcome_badge", "ip_address", "risk_score")
    list_filter = ("outcome",)
    search_fields = ("identifier", "ip_address", "device_fingerprint")
    readonly_fields = [f.name for f in LoginAttempt._meta.fields]
    date_hierarchy = "created_at"

    @admin.display(description="Outcome")
    def outcome_badge(self, obj):
        color = "#16a34a" if obj.was_successful else "#dc2626"
        return format_html('<span style="color:{};font-weight:600">{}</span>',
                           color, obj.get_outcome_display())

    def has_add_permission(self, request):
        return False


@admin.register(MFASecret)
class MFASecretAdmin(admin.ModelAdmin):
    list_display = ("user", "is_confirmed", "confirmed_at", "recovery_codes_remaining")
    list_filter = ("is_confirmed",)
    search_fields = ("user__email",)
    # The shared secret must never be visible in the admin.
    exclude = ("secret", "recovery_codes")
    readonly_fields = ("user", "is_confirmed", "confirmed_at", "last_used_counter")


@admin.register(SocialAccount)
class SocialAccountAdmin(admin.ModelAdmin):
    list_display = ("user", "provider", "email", "connected_at")
    list_filter = ("provider",)
    search_fields = ("user__email", "provider_uid", "email")


@admin.register(ActiveSession)
class ActiveSessionAdmin(admin.ModelAdmin):
    list_display = ("user", "ip_address", "last_seen_at", "expires_at", "revoked_at")
    search_fields = ("user__email", "ip_address")
    readonly_fields = ("id", "session_key", "jti", "created_at")
