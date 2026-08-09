"""Upload path helpers.

Files are namespaced per user and per module so a bucket can later be split
along the same boundaries as the services.
"""
import uuid
from pathlib import Path


def _build(prefix, instance, filename, owner_attr="user"):
    owner = getattr(instance, owner_attr, None)
    owner_id = getattr(owner, "id", "anonymous")
    suffix = Path(filename).suffix.lower() or ".bin"
    return f"{prefix}/{owner_id}/{uuid.uuid4().hex}{suffix}"


def profile_photo_path(instance, filename):
    return _build("profiles/photos", instance, filename)


def avatar_path(instance, filename):
    return _build("profiles/avatars", instance, filename)


def chat_attachment_path(instance, filename):
    return _build("chat/attachments", instance, filename, owner_attr="sender")


def voice_note_path(instance, filename):
    return _build("chat/voice", instance, filename, owner_attr="sender")


def chat_video_path(instance, filename):
    return _build("chat/videos", instance, filename, owner_attr="sender")


def chat_document_path(instance, filename):
    return _build("chat/documents", instance, filename, owner_attr="sender")


def verification_document_path(instance, filename):
    return _build("verification/private", instance, filename)


def report_evidence_path(instance, filename):
    return _build("reports/evidence", instance, filename, owner_attr="reporter")


def media_asset_path(instance, filename):
    return _build("media/assets", instance, filename, owner_attr="owner")
