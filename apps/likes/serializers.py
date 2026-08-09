"""Serializers for the likes REST surface."""
from rest_framework import serializers

from .models import Like, LikeType


class SwipeSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=LikeType.choices, default=LikeType.LIKE)
    message = serializers.CharField(required=False, allow_blank=True, max_length=200)
    source = serializers.CharField(required=False, allow_blank=True, max_length=30)

    def validate(self, attrs):
        if attrs.get("message") and attrs.get("kind") != LikeType.SUPER_LIKE:
            raise serializers.ValidationError(
                {"message": "A note can only be attached to a super like."}
            )
        return attrs


class LikeSerializer(serializers.ModelSerializer):
    is_positive = serializers.BooleanField(read_only=True)

    class Meta:
        model = Like
        fields = ["id", "sender", "receiver", "kind", "message",
                  "score_at_swipe", "is_positive", "created_at"]
        read_only_fields = fields


class QuotaSerializer(serializers.Serializer):
    likes_used = serializers.IntegerField()
    likes_limit = serializers.IntegerField(allow_null=True)
    likes_remaining = serializers.IntegerField(allow_null=True)
    super_likes_used = serializers.IntegerField()
    super_likes_limit = serializers.IntegerField(allow_null=True)
    super_likes_remaining = serializers.IntegerField(allow_null=True)
    rewinds_used = serializers.IntegerField()
    rewinds_limit = serializers.IntegerField(allow_null=True)
    rewinds_remaining = serializers.IntegerField(allow_null=True)
    is_unlimited = serializers.BooleanField()
