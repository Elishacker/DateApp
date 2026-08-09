from django.contrib import admin

from .models import CompatibilityScore, MatchingRun


@admin.register(CompatibilityScore)
class CompatibilityScoreAdmin(admin.ModelAdmin):
    list_display = ("seeker", "candidate", "score", "distance_km", "expires_at")
    list_filter = ("score",)
    search_fields = ("seeker__email", "candidate__email")
    readonly_fields = ("id", "breakdown", "created_at", "updated_at")


@admin.register(MatchingRun)
class MatchingRunAdmin(admin.ModelAdmin):
    list_display = ("seeker", "candidates_considered", "candidates_scored",
                    "top_score", "duration_ms", "created_at")
    search_fields = ("seeker__email",)
    readonly_fields = [f.name for f in MatchingRun._meta.fields]
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False
