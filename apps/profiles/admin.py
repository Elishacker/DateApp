from django.contrib import admin
from django.utils.html import format_html

from .models import Interest, MatchPreference, Profile, ProfilePhoto, ProfileView


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "headline", "gender", "city", "country",
                    "completion_score", "photo_count", "is_visible")
    list_filter = ("gender", "is_visible", "relationship_goal", "education_level", "country")
    search_fields = ("user__email", "user__username", "headline", "city", "job_title")
    filter_horizontal = ("interests",)
    readonly_fields = ("completion_score", "photo_count", "primary_photo_url",
                       "created_at", "updated_at")
    # Photos hang off User, not Profile, so they get their own admin page
    # rather than an inline that Django cannot resolve.

    fieldsets = (
        ("Presentation", {"fields": ("user", "headline", "bio", "gender", "pronouns", "height_cm")}),
        ("Work & study", {"fields": ("job_title", "company", "education_level", "school")}),
        ("Lifestyle", {"fields": ("smoking", "drinking", "exercise", "children",
                                  "religion", "languages", "relationship_goal")}),
        ("Interests", {"fields": ("interests",)}),
        ("Location", {"fields": ("city", "region", "country", "latitude",
                                 "longitude", "location_updated_at")}),
        ("Derived", {"fields": ("completion_score", "photo_count", "primary_photo_url",
                                "is_visible", "is_boosted_until")}),
    )


@admin.register(ProfilePhoto)
class ProfilePhotoAdmin(admin.ModelAdmin):
    list_display = ("preview", "user", "position", "is_primary", "moderation_status", "created_at")
    list_filter = ("moderation_status", "is_primary")
    search_fields = ("user__email",)
    actions = ["approve_photos", "reject_photos"]

    @admin.display(description="Photo")
    def preview(self, obj):
        if obj.url:
            return format_html('<img src="{}" style="height:48px;border-radius:6px">', obj.url)
        return "—"

    @admin.action(description="Approve selected photos")
    def approve_photos(self, request, queryset):
        from .services import PhotoService

        for photo in queryset:
            PhotoService.apply_moderation(photo.id, True, "Approved in admin")
        self.message_user(request, f"{queryset.count()} photo(s) approved.")

    @admin.action(description="Reject selected photos")
    def reject_photos(self, request, queryset):
        from .services import PhotoService

        for photo in queryset:
            PhotoService.apply_moderation(photo.id, False, "Rejected in admin")
        self.message_user(request, f"{queryset.count()} photo(s) rejected.")


@admin.register(Interest)
class InterestAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "emoji", "usage_count", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(MatchPreference)
class MatchPreferenceAdmin(admin.ModelAdmin):
    list_display = ("user", "min_age", "max_age", "max_distance_km",
                    "verified_only", "show_me_globally")
    list_filter = ("verified_only", "with_photos_only", "show_me_globally")
    search_fields = ("user__email",)


@admin.register(ProfileView)
class ProfileViewAdmin(admin.ModelAdmin):
    list_display = ("viewer", "viewed", "source", "created_at")
    list_filter = ("source",)
    search_fields = ("viewer__email", "viewed__email")
    date_hierarchy = "created_at"
