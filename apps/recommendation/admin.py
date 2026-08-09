from django.contrib import admin

from .models import Recommendation


@admin.register(Recommendation)
class RecommendationAdmin(admin.ModelAdmin):
    list_display = ("user", "candidate_id", "set_name", "rank", "score",
                    "was_shown", "was_acted_on", "expires_at")
    list_filter = ("set_name", "was_shown", "was_acted_on")
    search_fields = ("user__email", "candidate_id")
    readonly_fields = ("id", "created_at", "updated_at")
