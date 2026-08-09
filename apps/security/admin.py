from django.contrib import admin
from django.utils.html import format_html

from .models import IPReputation, RateLimitBreach, SecurityEvent


@admin.register(SecurityEvent)
class SecurityEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "kind", "severity_badge", "user",
                    "ip_address", "risk_score", "is_resolved")
    list_filter = ("kind", "severity", "is_resolved")
    search_fields = ("user__email", "ip_address", "description")
    date_hierarchy = "created_at"
    readonly_fields = [f.name for f in SecurityEvent._meta.fields
                       if f.name not in {"is_resolved", "resolution_note"}]
    actions = ["mark_resolved"]

    @admin.display(description="Severity")
    def severity_badge(self, obj):
        colors = {"critical": "#dc2626", "high": "#ea580c",
                  "medium": "#ca8a04", "low": "#64748b", "info": "#94a3b8"}
        return format_html('<span style="color:{};font-weight:700">{}</span>',
                           colors.get(obj.severity, "#334155"), obj.severity.upper())

    @admin.action(description="Mark selected events resolved")
    def mark_resolved(self, request, queryset):
        for event in queryset:
            event.resolve("Resolved in admin")
        self.message_user(request, f"{queryset.count()} event(s) resolved.")

    def has_add_permission(self, request):
        return False


@admin.register(IPReputation)
class IPReputationAdmin(admin.ModelAdmin):
    list_display = ("ip_address", "score", "failed_logins", "blocked_requests",
                    "is_blocked", "blocked_until", "last_seen_at")
    list_filter = ("is_blocked",)
    search_fields = ("ip_address", "notes")
    actions = ["block_ips", "unblock_ips"]

    @admin.action(description="Block selected IPs for 24 hours")
    def block_ips(self, request, queryset):
        from django.utils import timezone

        updated = queryset.update(
            is_blocked=True, blocked_until=timezone.now() + timezone.timedelta(hours=24)
        )
        self.message_user(request, f"{updated} IP(s) blocked.")

    @admin.action(description="Unblock selected IPs")
    def unblock_ips(self, request, queryset):
        updated = queryset.update(is_blocked=False, blocked_until=None, score=50)
        self.message_user(request, f"{updated} IP(s) unblocked.")


@admin.register(RateLimitBreach)
class RateLimitBreachAdmin(admin.ModelAdmin):
    list_display = ("created_at", "scope", "identifier", "path", "hits", "limit")
    list_filter = ("scope",)
    search_fields = ("identifier", "path", "ip_address")
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False
