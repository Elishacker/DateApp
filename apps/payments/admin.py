from django.contrib import admin
from django.utils.html import format_html

from .models import Invoice, Payment, Refund, SavedPaymentMethod, WebhookEvent


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("reference", "user", "provider", "status_badge", "amount_label",
                    "purpose", "created_at", "completed_at")
    list_filter = ("status", "provider", "purpose", "currency")
    search_fields = ("reference", "provider_reference", "user__email", "payer_phone")
    date_hierarchy = "created_at"
    readonly_fields = ("id", "reference", "provider_reference", "net_amount",
                       "created_at", "updated_at", "completed_at")
    actions = ["poll_provider_status"]

    @admin.display(description="Status")
    def status_badge(self, obj):
        colors = {"succeeded": "#16a34a", "pending": "#ca8a04", "processing": "#0284c7",
                  "failed": "#dc2626", "cancelled": "#64748b", "refunded": "#7c3aed"}
        return format_html('<span style="color:{};font-weight:600">{}</span>',
                           colors.get(obj.status, "#334155"), obj.get_status_display())

    @admin.action(description="Poll provider for current status")
    def poll_provider_status(self, request, queryset):
        from .services import PaymentService

        updated = 0
        for payment in queryset:
            try:
                PaymentService.poll_status(payment)
                updated += 1
            except Exception as exc:  # noqa: BLE001
                self.message_user(request, f"{payment.reference}: {exc}", level="ERROR")
        self.message_user(request, f"{updated} payment(s) polled.")


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("number", "user", "description", "total_label", "issued_at")
    search_fields = ("number", "user__email", "billing_email")
    date_hierarchy = "issued_at"
    readonly_fields = [f.name for f in Invoice._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Refund)
class RefundAdmin(admin.ModelAdmin):
    list_display = ("payment", "amount", "reason", "issued_by", "is_complete", "created_at")
    search_fields = ("payment__reference",)
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ("provider", "event_type", "external_id", "signature_verified",
                    "is_processed", "created_at")
    list_filter = ("provider", "is_processed", "signature_verified")
    search_fields = ("external_id", "event_type")
    date_hierarchy = "created_at"
    readonly_fields = [f.name for f in WebhookEvent._meta.fields]
    actions = ["replay_events"]

    @admin.action(description="Replay selected webhooks")
    def replay_events(self, request, queryset):
        import json

        from .services import WebhookService

        for event in queryset:
            WebhookService.receive(
                event.provider, json.dumps(event.payload).encode(), event.headers or {}
            )
        self.message_user(request, f"{queryset.count()} webhook(s) replayed.")

    def has_add_permission(self, request):
        return False


@admin.register(SavedPaymentMethod)
class SavedPaymentMethodAdmin(admin.ModelAdmin):
    list_display = ("user", "provider", "brand", "last_four", "is_default", "created_at")
    list_filter = ("provider", "is_default")
    search_fields = ("user__email",)
    exclude = ("token",)  # never surface the gateway token in the admin
