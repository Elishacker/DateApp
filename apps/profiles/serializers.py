"""Serializers for the profiles REST surface."""
from rest_framework import serializers

from .models import Interest, MatchPreference, Profile, ProfilePhoto


class InterestSerializer(serializers.ModelSerializer):
    class Meta:
        model = Interest
        fields = ["id", "name", "slug", "category", "emoji"]


class ProfilePhotoSerializer(serializers.ModelSerializer):
    url = serializers.CharField(read_only=True)
    is_public = serializers.BooleanField(read_only=True)

    class Meta:
        model = ProfilePhoto
        fields = ["id", "url", "caption", "position", "is_primary",
                  "moderation_status", "is_public", "created_at"]
        read_only_fields = ["id", "url", "position", "moderation_status",
                            "is_public", "created_at"]


class PhotoUploadSerializer(serializers.Serializer):
    image = serializers.ImageField()
    caption = serializers.CharField(required=False, allow_blank=True, max_length=140)
    make_primary = serializers.BooleanField(required=False, default=False)


class PhotoReorderSerializer(serializers.Serializer):
    order = serializers.ListField(child=serializers.UUIDField(), min_length=1)


class ProfileSerializer(serializers.ModelSerializer):
    interests = InterestSerializer(many=True, read_only=True)
    interest_ids = serializers.ListField(
        child=serializers.CharField(), write_only=True, required=False,
        help_text="Interest UUIDs or plain names.",
    )
    photos = serializers.SerializerMethodField()
    age = serializers.IntegerField(read_only=True)
    location_label = serializers.CharField(read_only=True)
    is_boosted = serializers.BooleanField(read_only=True)

    class Meta:
        model = Profile
        fields = [
            "user_id", "headline", "bio", "gender", "pronouns", "height_cm",
            "job_title", "company", "education_level", "school",
            "smoking", "drinking", "exercise", "children", "religion",
            "languages", "relationship_goal", "interests", "interest_ids",
            "city", "region", "country", "latitude", "longitude",
            "location_label", "completion_score", "photo_count",
            "primary_photo_url", "photos", "age", "is_visible", "is_boosted",
        ]
        read_only_fields = [
            "user_id", "completion_score", "photo_count",
            "primary_photo_url", "age", "is_boosted",
        ]

    def get_photos(self, obj):
        photos = obj.user.photos.filter(
            moderation_status=ProfilePhoto.ModerationStatus.APPROVED
        ).order_by("-is_primary", "position")
        return ProfilePhotoSerializer(photos, many=True).data


class PublicProfileSerializer(serializers.Serializer):
    """Everything a viewer may see about someone else."""

    user = serializers.DictField()
    profile = serializers.DictField()
    distance_km = serializers.FloatField(allow_null=True)
    compatibility = serializers.IntegerField(allow_null=True)
    is_match = serializers.BooleanField(default=False)
    has_liked = serializers.BooleanField(default=False)


class MatchPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = MatchPreference
        exclude = ["created_at", "updated_at"]
        read_only_fields = ["user"]

    def validate(self, attrs):
        min_age = attrs.get("min_age", getattr(self.instance, "min_age", 18))
        max_age = attrs.get("max_age", getattr(self.instance, "max_age", 45))
        if min_age > max_age:
            raise serializers.ValidationError(
                {"min_age": "Minimum age cannot exceed maximum age."}
            )
        if min_age < 18:
            raise serializers.ValidationError({"min_age": "Zynora is strictly 18+."})
        return attrs


class LocationSerializer(serializers.Serializer):
    latitude = serializers.FloatField(min_value=-90, max_value=90)
    longitude = serializers.FloatField(min_value=-180, max_value=180)
    city = serializers.CharField(required=False, allow_blank=True, max_length=120)
    region = serializers.CharField(required=False, allow_blank=True, max_length=120)
    country = serializers.CharField(required=False, allow_blank=True, max_length=80)
