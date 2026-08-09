"""Serializers for the moderation REST surface."""
from rest_framework import serializers

from .models import ModerationCase


class ModerationDecisionSerializer(serializers.Serializer):
    case_id = serializers.UUIDField()
    approved = serializers.BooleanField()
    note = serializers.CharField(required=False, allow_blank=True, max_length=400)


class ScreenTextSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=4000)


class ModerationCaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = ModerationCase
        fields = ["id", "owner_id", "object_type", "object_id", "content_url",
                  "content_snapshot", "status", "severity", "reasons",
                  "risk_score", "created_at", "reviewed_at"]
        read_only_fields = fields
