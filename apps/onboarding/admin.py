from django.contrib import admin

from .models import OnboardingProgress


@admin.register(OnboardingProgress)
class OnboardingProgressAdmin(admin.ModelAdmin):
    list_display = ("user", "current_step", "percent_complete", "is_complete", "completed_at")
    list_filter = ("is_complete", "current_step")
    search_fields = ("user__email", "user__username")
    readonly_fields = ("percent_complete", "created_at", "updated_at")
