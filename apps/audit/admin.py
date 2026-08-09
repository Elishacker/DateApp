from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Read-only by design — the trail is evidence, not editable data."""

    list_display = ("created_at", "action", "category", "actor_label",
                    "object_type", "object_id", "ip_address")
    list_filter = ("category", "is_sensitive", "action")
    search_fields = ("action", "actor_label", "description", "object_id", "ip_address")
    date_hierarchy = "created_at"
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if not request.user.is_superuser:
            qs = qs.filter(is_sensitive=False)
        return qs

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
