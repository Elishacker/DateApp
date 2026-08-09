from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.utils.html import format_html

from .models import Device, User, UserSettings


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ("email", "username", "status_badge", "role", "verification_level",
                    "has_completed_onboarding", "is_online", "date_joined")
    list_filter = ("status", "role", "is_staff", "is_email_verified",
                   "has_completed_onboarding", "is_online")
    search_fields = ("email", "username", "first_name", "last_name", "phone")
    ordering = ("-date_joined",)
    readonly_fields = ("id", "date_joined", "last_login", "last_active_at",
                       "password_changed_at", "avatar_url")

    fieldsets = (
        (None, {"fields": ("id", "email", "username", "password")}),
        ("Personal", {"fields": ("first_name", "last_name", "phone", "date_of_birth", "avatar_url")}),
        ("Account state", {"fields": ("status", "role", "is_active", "has_completed_onboarding",
                                      "onboarding_step", "deactivated_at", "deletion_requested_at")}),
        ("Verification", {"fields": ("is_email_verified", "is_phone_verified", "is_photo_verified",
                                     "is_identity_verified", "verification_level")}),
        ("Security", {"fields": ("is_mfa_enabled", "failed_login_attempts", "locked_until",
                                 "must_change_password", "password_changed_at", "last_login_ip")}),
        ("Permissions", {"fields": ("is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Activity", {"fields": ("is_online", "last_active_at", "last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "username", "password1", "password2", "first_name", "date_of_birth"),
        }),
    )

    @admin.display(description="Status")
    def status_badge(self, obj):
        colors = {"active": "#16a34a", "pending": "#ca8a04",
                  "suspended": "#ea580c", "banned": "#dc2626", "deactivated": "#64748b"}
        return format_html(
            '<span style="color:{};font-weight:600">{}</span>',
            colors.get(obj.status, "#334155"), obj.get_status_display(),
        )

    actions = ["activate_accounts", "suspend_accounts"]

    @admin.action(description="Activate selected accounts")
    def activate_accounts(self, request, queryset):
        updated = queryset.update(status="active", is_active=True)
        self.message_user(request, f"{updated} account(s) activated.")

    @admin.action(description="Suspend selected accounts")
    def suspend_accounts(self, request, queryset):
        updated = queryset.update(status="suspended", is_online=False)
        self.message_user(request, f"{updated} account(s) suspended.")


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ("user", "name", "platform", "ip_address", "is_trusted",
                    "last_seen_at", "revoked_at")
    list_filter = ("platform", "is_trusted")
    search_fields = ("user__email", "fingerprint", "ip_address")
    readonly_fields = ("id", "fingerprint", "user_agent", "created_at")


@admin.register(UserSettings)
class UserSettingsAdmin(admin.ModelAdmin):
    list_display = ("user", "language", "theme", "incognito_mode", "push_notifications")
    list_filter = ("language", "theme", "incognito_mode")
    search_fields = ("user__email",)
