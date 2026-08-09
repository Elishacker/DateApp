"""Serializers for the REST wizard."""
from rest_framework import serializers

from apps.common.constants import Gender, RelationshipGoal


class IdentitySerializer(serializers.Serializer):
    gender = serializers.ChoiceField(choices=Gender.choices)
    headline = serializers.CharField(required=False, allow_blank=True, max_length=120)
    bio = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    relationship_goal = serializers.ChoiceField(
        choices=RelationshipGoal.choices, required=False, allow_blank=True
    )
    job_title = serializers.CharField(required=False, allow_blank=True, max_length=120)
    school = serializers.CharField(required=False, allow_blank=True, max_length=150)


class InterestsSerializer(serializers.Serializer):
    interests = serializers.ListField(child=serializers.CharField(), min_length=3, max_length=15)


class PreferencesSerializer(serializers.Serializer):
    interested_in = serializers.ListField(
        child=serializers.ChoiceField(choices=Gender.choices), required=False
    )
    min_age = serializers.IntegerField(min_value=18, max_value=99, required=False)
    max_age = serializers.IntegerField(min_value=18, max_value=99, required=False)
    max_distance_km = serializers.IntegerField(min_value=1, max_value=500, required=False)
    preferred_relationship_goals = serializers.ListField(
        child=serializers.ChoiceField(choices=RelationshipGoal.choices), required=False
    )

    def validate(self, attrs):
        if attrs.get("min_age") and attrs.get("max_age"):
            if attrs["min_age"] > attrs["max_age"]:
                raise serializers.ValidationError(
                    {"min_age": "Minimum age cannot exceed maximum age."}
                )
        return attrs


class LocationSerializer(serializers.Serializer):
    latitude = serializers.FloatField(min_value=-90, max_value=90, required=False, allow_null=True)
    longitude = serializers.FloatField(min_value=-180, max_value=180, required=False, allow_null=True)
    city = serializers.CharField(required=False, allow_blank=True, max_length=120)
    country = serializers.CharField(required=False, allow_blank=True, max_length=80)
