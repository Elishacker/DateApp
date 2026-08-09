from django.contrib import admin
from django.utils.html import format_html

from .models import Block, Report, SupportTicket


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("urgency", "reported", "reporter", "reason",
                    "status", "outcome", "created_at")
    list_filter = ("status", "reason", "outcome", "is_urgent")
    search_fields = ("reporter__email", "reported__email", "description")
    date_hierarchy = "created_at"
    readonly_fields = ("id", "created_at", "updated_at")

    @admin.display(description="")
    def urgency(self, obj):
        if obj.is_urgent:
            return format_html('<span style="color:#dc2626;font-weight:700">URGENT</span>')
        return ""


@admin.register(Block)
class BlockAdmin(admin.ModelAdmin):
    list_display = ("blocker", "blocked", "from_report", "created_at")
    list_filter = ("from_report",)
    search_fields = ("blocker__email", "blocked__email")
    date_hierarchy = "created_at"


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = ("number", "user", "category", "subject",
                    "status", "is_priority", "created_at")
    list_filter = ("status", "category", "is_priority")
    search_fields = ("number", "user__email", "subject")
    date_hierarchy = "created_at"
    readonly_fields = ("id", "number", "created_at", "updated_at")
