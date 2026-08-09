from django.contrib import admin

from .models import Match


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ("user_low", "user_high", "status", "origin",
                    "compatibility_score", "message_count", "matched_at")
    list_filter = ("status", "origin", "has_conversation")
    search_fields = ("user_low__email", "user_high__email")
    date_hierarchy = "matched_at"
    readonly_fields = ("id", "created_at", "updated_at", "compatibility_score")
