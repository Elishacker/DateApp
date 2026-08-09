"""Serializers for the chat REST surface."""
from rest_framework import serializers

from .models import Conversation, Message, MessageType


class MessageSerializer(serializers.ModelSerializer):
    attachment_url = serializers.CharField(read_only=True)
    voice_url = serializers.CharField(read_only=True)

    class Meta:
        model = Message
        fields = ["id", "conversation", "sender", "kind", "body", "attachment_url",
                  "voice_url", "voice_duration_seconds", "gif_url", "reply_to",
                  "is_read", "is_edited", "is_deleted", "created_at"]
        read_only_fields = fields


class SendMessageSerializer(serializers.Serializer):
    body = serializers.CharField(required=False, allow_blank=True, max_length=4000)
    kind = serializers.ChoiceField(choices=MessageType.choices, default=MessageType.TEXT)
    attachment = serializers.ImageField(required=False)
    voice_note = serializers.FileField(required=False)
    video = serializers.FileField(required=False)
    document = serializers.FileField(required=False)
    voice_duration_seconds = serializers.IntegerField(required=False, min_value=1, max_value=300)
    gif_url = serializers.URLField(required=False, allow_blank=True)
    reply_to = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, attrs):
        kind = attrs.get("kind", MessageType.TEXT)
        if kind == MessageType.TEXT and not (attrs.get("body") or "").strip():
            raise serializers.ValidationError({"body": "Write something first."})
        if kind == MessageType.IMAGE and not attrs.get("attachment"):
            raise serializers.ValidationError({"attachment": "Attach an image."})
        if kind == MessageType.VOICE and not attrs.get("voice_note"):
            raise serializers.ValidationError({"voice_note": "Attach a voice note."})
        if kind == MessageType.VIDEO and not attrs.get("video"):
            raise serializers.ValidationError({"video": "Attach a video."})
        if kind == MessageType.DOCUMENT and not attrs.get("document"):
            raise serializers.ValidationError({"document": "Attach a document."})
        if kind == MessageType.GIF and not attrs.get("gif_url"):
            raise serializers.ValidationError({"gif_url": "Provide a GIF URL."})
        return attrs


class ConversationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Conversation
        fields = ["id", "match_id", "is_active", "last_message_at",
                  "last_message_preview", "message_count", "created_at"]
        read_only_fields = fields


class ReactionSerializer(serializers.Serializer):
    emoji = serializers.CharField(max_length=8)
