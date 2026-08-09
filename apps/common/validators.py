"""Reusable field validators."""
import re
from datetime import date

from django.conf import settings
from django.core.exceptions import ValidationError

PHONE_RE = re.compile(r"^\+?[1-9]\d{7,14}$")
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.]{3,30}$")

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic"}
ALLOWED_VIDEO_TYPES = {"video/mp4", "video/webm", "video/quicktime"}
ALLOWED_DOCUMENT_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/plain",
}
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_AUDIO_BYTES = 12 * 1024 * 1024
MAX_VIDEO_BYTES = 50 * 1024 * 1024
MAX_DOCUMENT_BYTES = 15 * 1024 * 1024


def validate_phone(value):
    if not PHONE_RE.match(str(value)):
        raise ValidationError("Enter a valid phone number in international format, e.g. +255712345678.")


def validate_username(value):
    if not USERNAME_RE.match(str(value)):
        raise ValidationError("Usernames use 3-30 letters, digits, underscores or dots.")


def validate_adult(value):
    """Age gate — the platform is 18+ and this is enforced at the model layer."""
    if not isinstance(value, date):
        raise ValidationError("Enter a valid date of birth.")
    today = date.today()
    age = today.year - value.year - ((today.month, today.day) < (value.month, value.day))
    min_age = settings.ZYNORA["MIN_AGE"]
    if age < min_age:
        raise ValidationError(f"You must be at least {min_age} years old to use Zynora.")
    if age > settings.ZYNORA["MAX_AGE"]:
        raise ValidationError("Enter a valid date of birth.")


def validate_image_file(uploaded):
    if uploaded.size > MAX_IMAGE_BYTES:
        raise ValidationError("Images must be 8 MB or smaller.")
    content_type = getattr(uploaded, "content_type", None)
    if content_type and content_type not in ALLOWED_IMAGE_TYPES:
        raise ValidationError("Upload a JPEG, PNG, WEBP or HEIC image.")


def validate_audio_file(uploaded):
    if uploaded.size > MAX_AUDIO_BYTES:
        raise ValidationError("Voice notes must be 12 MB or smaller.")


def validate_video_file(uploaded):
    if uploaded.size > MAX_VIDEO_BYTES:
        raise ValidationError("Videos must be 50 MB or smaller.")
    content_type = getattr(uploaded, "content_type", None)
    if content_type and content_type not in ALLOWED_VIDEO_TYPES:
        raise ValidationError("Upload an MP4, WEBM or MOV video.")


def validate_document_file(uploaded):
    if uploaded.size > MAX_DOCUMENT_BYTES:
        raise ValidationError("Documents must be 15 MB or smaller.")
    content_type = getattr(uploaded, "content_type", None)
    if content_type and content_type not in ALLOWED_DOCUMENT_TYPES:
        raise ValidationError("Upload a PDF, Word, Excel or plain text document.")


def validate_latitude(value):
    if value is not None and not (-90 <= float(value) <= 90):
        raise ValidationError("Latitude must be between -90 and 90.")


def validate_longitude(value):
    if value is not None and not (-180 <= float(value) <= 180):
        raise ValidationError("Longitude must be between -180 and 180.")
