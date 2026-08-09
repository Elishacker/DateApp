"""Replace stored emoji with sprite icon names.

``Notification.icon`` is a denormalised copy of the icon for its kind. Rows
written before the platform moved to Bootstrap Icons still hold emoji, which the
``{% icon %}`` tag cannot resolve — they would render as nothing at all.

Recomputing from ``kind`` rather than mapping emoji-to-name is deliberate: it is
self-healing, so re-running it after any future icon change fixes history too.
"""
from django.db import migrations

#: Mirrors KIND_RULES in apps/notifications/services.py. Duplicated here on
#: purpose — a migration must keep working even when that module changes.
KIND_ICONS = {
    "match": "chat-heart-fill",
    "like": "heart-fill",
    "super_like": "star-fill",
    "message": "chat-dots-fill",
    "profile_view": "eye-fill",
    "verification": "patch-check-fill",
    "subscription": "gem",
    "payment": "receipt",
    "security": "shield-lock-fill",
    "moderation": "exclamation-triangle-fill",
    "system": "bell-fill",
}
FALLBACK = "bell-fill"


def to_icon_names(apps, schema_editor):
    Notification = apps.get_model("notifications", "Notification")
    for kind, name in KIND_ICONS.items():
        Notification.objects.filter(kind=kind).exclude(icon=name).update(icon=name)
    # Anything with an unrecognised kind still needs a resolvable icon.
    Notification.objects.exclude(kind__in=KIND_ICONS).update(icon=FALLBACK)


def noop(apps, schema_editor):
    """No reverse: the emoji carried no information the kind does not."""


class Migration(migrations.Migration):
    dependencies = [("notifications", "0001_initial")]
    operations = [migrations.RunPython(to_icon_names, noop)]
