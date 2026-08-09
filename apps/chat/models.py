"""Conversations, messages and presence.

``chat`` is the module most likely to be pulled out into its own deployment
(different scaling profile, different storage engine), so it is deliberately the
most decoupled: it references a match by ``ServiceReference`` UUID only, and it
resolves participants through the matches contract rather than a join.
"""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel, ServiceReference, TimeStampedModel
from apps.common.storage import (
    chat_attachment_path,
    chat_document_path,
    chat_video_path,
    voice_note_path,
)
from apps.common.validators import (
    validate_audio_file,
    validate_document_file,
    validate_image_file,
    validate_video_file,
)


class Conversation(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # No FK: the match lives in another service's tables.
    match_id = ServiceReference("matches", null=True, blank=True)

    participants = models.ManyToManyField(
        settings.AUTH_USER_MODEL, related_name="conversations", through="ConversationMember"
    )

    is_active = models.BooleanField(default=True, db_index=True)
    last_message_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_message_preview = models.CharField(max_length=140, blank=True)
    message_count = models.PositiveIntegerField(default=0)
    closed_at = models.DateTimeField(null=True, blank=True)
    close_reason = models.CharField(max_length=140, blank=True)

    class Meta:
        db_table = "chat_conversation"
        ordering = ["-last_message_at", "-created_at"]
        indexes = [models.Index(fields=["match_id"]), models.Index(fields=["-last_message_at"])]

    def __str__(self):
        return f"Conversation {self.id}"

    def other_member(self, user_id):
        return self.members.exclude(user_id=user_id).first()


class ConversationMember(TimeStampedModel):
    """Per-participant state: unread counts, mute, typing, last read marker."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="members"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="conversation_memberships"
    )

    unread_count = models.PositiveIntegerField(default=0)
    last_read_at = models.DateTimeField(null=True, blank=True)
    last_typed_at = models.DateTimeField(null=True, blank=True)
    is_muted = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    left_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "chat_conversation_member"
        unique_together = [("conversation", "user")]
        indexes = [models.Index(fields=["user", "is_archived"])]

    def __str__(self):
        return f"{self.user_id} in {self.conversation_id}"

    @property
    def is_typing(self):
        if not self.last_typed_at:
            return False
        return (timezone.now() - self.last_typed_at).total_seconds() < 5


class MessageType(models.TextChoices):
    TEXT = "text", "Text"
    IMAGE = "image", "Image"
    VOICE = "voice", "Voice note"
    VIDEO = "video", "Video"
    DOCUMENT = "document", "Document"
    GIF = "gif", "GIF"
    SYSTEM = "system", "System"


class Message(BaseModel):
    """Soft-deleted so a removed message still shows as 'deleted' to the peer."""

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="messages_sent"
    )

    kind = models.CharField(max_length=10, choices=MessageType.choices, default=MessageType.TEXT)
    body = models.TextField(max_length=4000, blank=True)

    attachment = models.ImageField(
        upload_to=chat_attachment_path, blank=True, null=True, validators=[validate_image_file]
    )
    voice_note = models.FileField(
        upload_to=voice_note_path, blank=True, null=True, validators=[validate_audio_file]
    )
    voice_duration_seconds = models.PositiveSmallIntegerField(null=True, blank=True)
    video = models.FileField(
        upload_to=chat_video_path, blank=True, null=True, validators=[validate_video_file]
    )
    document = models.FileField(
        upload_to=chat_document_path, blank=True, null=True, validators=[validate_document_file]
    )
    #: Upload paths are UUID-named, so the original name is kept for display.
    document_name = models.CharField(max_length=255, blank=True)
    gif_url = models.URLField(blank=True)

    reply_to = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="replies"
    )

    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    is_edited = models.BooleanField(default=False)
    edited_at = models.DateTimeField(null=True, blank=True)

    is_flagged = models.BooleanField(default=False, db_index=True)
    moderation_note = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "chat_message"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["conversation", "-created_at"]),
            models.Index(fields=["sender", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.kind} from {self.sender_id}"

    @property
    def attachment_url(self):
        try:
            return self.attachment.url if self.attachment else ""
        except ValueError:
            return ""

    @property
    def voice_url(self):
        try:
            return self.voice_note.url if self.voice_note else ""
        except ValueError:
            return ""

    @property
    def video_url(self):
        try:
            return self.video.url if self.video else ""
        except ValueError:
            return ""

    @property
    def document_url(self):
        try:
            return self.document.url if self.document else ""
        except ValueError:
            return ""

    def mark_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=["is_read", "read_at"])


class MessageReaction(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="reactions")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="message_reactions"
    )
    emoji = models.CharField(max_length=8)

    class Meta:
        db_table = "chat_message_reaction"
        unique_together = [("message", "user", "emoji")]

    def __str__(self):
        return f"{self.emoji} by {self.user_id}"
