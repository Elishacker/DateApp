"""Dating profile, photo gallery, interest catalogue and match preferences.

``profiles`` owns everything a member *presents* and everything they are
*looking for*. Discovery and matching read this through the interface — they
never touch these tables.
"""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.constants import (
    ChildrenStatus,
    EducationLevel,
    Gender,
    LifestyleChoice,
    RelationshipGoal,
)
from apps.common.models import BaseModel, TimeStampedModel
from apps.common.storage import profile_photo_path
from apps.common.utils import calculate_age
from apps.common.validators import (
    validate_image_file,
    validate_latitude,
    validate_longitude,
)


class Interest(TimeStampedModel):
    """Shared catalogue. Seeded by ``manage.py seed_demo``."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(max_length=70, unique=True)
    category = models.CharField(max_length=40, default="lifestyle", db_index=True)
    emoji = models.CharField(max_length=8, blank=True)
    is_active = models.BooleanField(default=True)
    usage_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "profiles_interest"
        ordering = ["category", "name"]

    def __str__(self):
        return self.name


class Profile(TimeStampedModel):
    """One-to-one with the user; the public face of a member."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="profile", primary_key=True,
    )

    headline = models.CharField(max_length=120, blank=True)
    bio = models.TextField(max_length=2000, blank=True)
    gender = models.CharField(max_length=20, choices=Gender.choices, blank=True, db_index=True)
    pronouns = models.CharField(max_length=40, blank=True)
    height_cm = models.PositiveSmallIntegerField(null=True, blank=True)

    # Work & study
    job_title = models.CharField(max_length=120, blank=True)
    company = models.CharField(max_length=120, blank=True)
    education_level = models.CharField(
        max_length=20, choices=EducationLevel.choices, blank=True, db_index=True
    )
    school = models.CharField(max_length=150, blank=True)

    # Lifestyle
    smoking = models.CharField(max_length=20, choices=LifestyleChoice.choices, blank=True)
    drinking = models.CharField(max_length=20, choices=LifestyleChoice.choices, blank=True)
    exercise = models.CharField(max_length=20, choices=LifestyleChoice.choices, blank=True)
    children = models.CharField(max_length=20, choices=ChildrenStatus.choices, blank=True)
    religion = models.CharField(max_length=60, blank=True)
    languages = models.JSONField(default=list, blank=True)
    relationship_goal = models.CharField(
        max_length=20, choices=RelationshipGoal.choices, blank=True, db_index=True
    )

    interests = models.ManyToManyField(Interest, blank=True, related_name="profiles")

    # Location. Coordinates are coarse by design — see LOCATION_PRECISION.
    city = models.CharField(max_length=120, blank=True, db_index=True)
    region = models.CharField(max_length=120, blank=True)
    country = models.CharField(max_length=80, blank=True, db_index=True)
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True, validators=[validate_latitude]
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True, validators=[validate_longitude]
    )
    location_updated_at = models.DateTimeField(null=True, blank=True)

    # Denormalised counters kept current by services/events.
    completion_score = models.PositiveSmallIntegerField(default=0, db_index=True)
    photo_count = models.PositiveSmallIntegerField(default=0)
    primary_photo_url = models.CharField(max_length=255, blank=True)

    is_visible = models.BooleanField(
        default=True, db_index=True,
        help_text="Off means the profile never appears in anyone's feed.",
    )
    is_boosted_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "profiles_profile"
        indexes = [
            models.Index(fields=["gender", "is_visible"]),
            models.Index(fields=["latitude", "longitude"]),
            models.Index(fields=["country", "city"]),
        ]

    def __str__(self):
        return f"Profile of {self.user_id}"

    # ---- derived ------------------------------------------------------------
    @property
    def age(self):
        return calculate_age(self.user.date_of_birth)

    @property
    def has_location(self):
        return self.latitude is not None and self.longitude is not None

    @property
    def is_boosted(self):
        return bool(self.is_boosted_until and self.is_boosted_until > timezone.now())

    @property
    def location_label(self):
        return ", ".join(p for p in (self.city, self.country) if p)

    @property
    def region_label(self):
        """Region and country, as shown on a discovery card.

        Falls back to city when no region is recorded — most members fill in a
        city and never touch the region field.
        """
        area = self.region or self.city
        return ", ".join(p for p in (area, self.country) if p)

    def interest_names(self):
        return list(self.interests.values_list("name", flat=True))

    # ---- completion ---------------------------------------------------------
    #: (weight, checker). Weights total 100.
    COMPLETION_RULES = (
        (20, lambda p: p.photo_count >= 1),
        (10, lambda p: p.photo_count >= 3),
        (15, lambda p: len(p.bio) >= 60),
        (10, lambda p: bool(p.headline)),
        (10, lambda p: bool(p.gender)),
        (10, lambda p: p.has_location),
        (10, lambda p: p.interests.count() >= 3),
        (5, lambda p: bool(p.job_title or p.school)),
        (5, lambda p: bool(p.relationship_goal)),
        (5, lambda p: bool(p.education_level)),
    )

    def calculate_completion(self):
        score = 0
        for weight, rule in self.COMPLETION_RULES:
            try:
                if rule(self):
                    score += weight
            except Exception:  # noqa: BLE001 - a broken rule must not break saving
                continue
        return min(score, 100)

    def refresh_completion(self):
        score = self.calculate_completion()
        if score != self.completion_score:
            self.completion_score = score
            self.save(update_fields=["completion_score", "updated_at"])
        return score


class ProfilePhoto(BaseModel):
    """Gallery entry. Ordering drives the card carousel in discovery."""

    class ModerationStatus(models.TextChoices):
        PENDING = "pending", "Awaiting review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="photos"
    )
    image = models.ImageField(upload_to=profile_photo_path, validators=[validate_image_file])
    caption = models.CharField(max_length=140, blank=True)
    position = models.PositiveSmallIntegerField(default=0, db_index=True)
    is_primary = models.BooleanField(default=False)

    moderation_status = models.CharField(
        max_length=12, choices=ModerationStatus.choices,
        default=ModerationStatus.PENDING, db_index=True,
    )
    moderation_note = models.CharField(max_length=255, blank=True)
    moderated_at = models.DateTimeField(null=True, blank=True)

    width = models.PositiveSmallIntegerField(null=True, blank=True)
    height = models.PositiveSmallIntegerField(null=True, blank=True)
    file_size = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "profiles_photo"
        ordering = ["position", "created_at"]
        indexes = [models.Index(fields=["user", "position"])]

    def __str__(self):
        return f"Photo {self.position} of {self.user_id}"

    @property
    def is_public(self):
        return self.moderation_status == self.ModerationStatus.APPROVED

    @property
    def url(self):
        try:
            return self.image.url
        except ValueError:
            return ""


class MatchPreference(TimeStampedModel):
    """What a member is looking for. The matching engine's primary input."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="preferences", primary_key=True,
    )

    interested_in = models.JSONField(
        default=list, blank=True, help_text="List of Gender values; empty means everyone."
    )
    min_age = models.PositiveSmallIntegerField(default=18)
    max_age = models.PositiveSmallIntegerField(default=45)
    max_distance_km = models.PositiveSmallIntegerField(default=100)

    # Soft filters — they shape the score rather than excluding candidates.
    preferred_relationship_goals = models.JSONField(default=list, blank=True)
    preferred_education_levels = models.JSONField(default=list, blank=True)
    preferred_languages = models.JSONField(default=list, blank=True)
    preferred_religion = models.CharField(max_length=60, blank=True)
    smoking_preference = models.CharField(max_length=20, choices=LifestyleChoice.choices, blank=True)
    drinking_preference = models.CharField(max_length=20, choices=LifestyleChoice.choices, blank=True)
    children_preference = models.CharField(max_length=20, choices=ChildrenStatus.choices, blank=True)

    # Hard filters — premium-gated in the UI, enforced in discovery.
    verified_only = models.BooleanField(default=False)
    with_photos_only = models.BooleanField(default=True)
    show_me_globally = models.BooleanField(default=False)

    class Meta:
        db_table = "profiles_match_preference"

    def __str__(self):
        return f"Preferences of {self.user_id}"

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.min_age > self.max_age:
            raise ValidationError({"min_age": "Minimum age cannot exceed maximum age."})

    def as_filter_dict(self):
        """Wire-safe shape consumed by discovery and matching."""
        return {
            "interested_in": list(self.interested_in or []),
            "min_age": self.min_age,
            "max_age": self.max_age,
            "max_distance_km": self.max_distance_km,
            "preferred_relationship_goals": list(self.preferred_relationship_goals or []),
            "preferred_education_levels": list(self.preferred_education_levels or []),
            "preferred_languages": list(self.preferred_languages or []),
            "preferred_religion": self.preferred_religion,
            "smoking_preference": self.smoking_preference,
            "drinking_preference": self.drinking_preference,
            "children_preference": self.children_preference,
            "verified_only": self.verified_only,
            "with_photos_only": self.with_photos_only,
            "show_me_globally": self.show_me_globally,
        }


class ProfileView(TimeStampedModel):
    """Who looked at whom. Powers 'viewed you' and the analytics funnel."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    viewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile_views_made"
    )
    viewed = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile_views_received"
    )
    source = models.CharField(max_length=30, default="discovery")

    class Meta:
        db_table = "profiles_profile_view"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["viewed", "-created_at"]),
            models.Index(fields=["viewer", "viewed"]),
        ]

    def __str__(self):
        return f"{self.viewer_id} viewed {self.viewed_id}"
