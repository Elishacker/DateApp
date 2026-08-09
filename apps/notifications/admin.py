from django.contrib import admin

from .models import DeliveryLog, Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "kind", "title", "is_read", "created_at")
    list_filter = ("kind", "is_read")
    search_fields = ("user__email", "title", "body")
    date_hierarchy = "created_at"
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(DeliveryLog)
class DeliveryLogAdmin(admin.ModelAdmin):
    list_display = ("user", "channel", "status", "template", "destination",
                    "attempts", "sent_at")
    list_filter = ("channel", "status")
    search_fields = ("user__email", "destination", "provider_reference")
    date_hierarchy = "created_at"
    readonly_fields = ("id", "created_at", "updated_at")
    actions = ["retry_delivery"]

    @admin.action(description="Retry selected deliveries")
    def retry_delivery(self, request, queryset):
        from .tasks import deliver_notification

        for log in queryset:
            deliver_notification.delay(str(log.id))
        self.message_user(request, f"{queryset.count()} delivery(s) re-queued.")
