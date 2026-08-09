"""Serializers for the verification REST surface.

Note there is no serializer exposing ``document`` — verification evidence is
never returned through the public API.
"""
from rest_framework import serializers

from apps.common.validators import validate_phone

from .models import VerificationKind, VerificationRequest


class SelfieUploadSerializer(serializers.Serializer):
    photo = serializers.ImageField()
    pose = serializers.CharField(required=False, allow_blank=True, max_length=60)
    kind = serializers.ChoiceField(
        choices=[VerificationKind.SELFIE, VerificationKind.GOVERNMENT_ID],
        default=VerificationKind.SELFIE,
    )


class PhoneStartSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=20, validators=[validate_phone])


class PhoneConfirmSerializer(serializers.Serializer):
    code = serializers.CharField(min_length=6, max_length=6)


class VerificationDecisionSerializer(serializers.Serializer):
    request_id = serializers.UUIDField()
    approved = serializers.BooleanField()
    reason = serializers.CharField(required=False, allow_blank=True, max_length=255)


class VerificationRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = VerificationRequest
        fields = ["id", "kind", "status", "challenge_pose", "rejection_reason",
                  "created_at", "reviewed_at"]
        read_only_fields = fields
