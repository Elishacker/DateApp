"""Public contract of the notifications service."""
from apps.common.interface import ModuleInterface

from .models import Channel, DeliveryLog, Notification, NotificationKind
from .services import NotificationService


class NotificationsInterface(ModuleInterface):
    name = "notifications"
    depends_on = ("accounts", "chat", "subscriptions")

    def notify(self, user_id, kind, *, title, body="", action_url="",
               actor_id=None, object_id=None, object_type="",
               metadata=None, channels=None):
        """Generic entry point for modules that need a bespoke notification."""
        notification = NotificationService.create(
            user_id, kind, title=title, body=body, action_url=action_url,
            actor_id=actor_id, object_id=object_id, object_type=object_type,
            metadata=metadata, channels=channels,
        )
        return str(notification.id) if notification else None

    def send_transactional_email(self, user_id, template, subject, context=None):
        """Direct email send that bypasses the inbox (verification, reset, …).

        The template context is stored on the log so the worker needs no extra
        lookups and a failed send can be retried verbatim.
        """
        from .tasks import deliver_notification

        log = DeliveryLog.objects.create(
            user_id=user_id, channel=Channel.EMAIL,
            template=template, subject=subject[:200], context=context or {},
        )
        deliver_notification.delay(str(log.id))
        return str(log.id)

    def get_unread_count(self, user_id):
        return NotificationService.unread_count(user_id)

    def list_notifications(self, user_id, unread_only=False, limit=50):
        return [
            NotificationService.serialize(n)
            for n in NotificationService.list_for(user_id, unread_only, limit)
        ]

    def mark_read(self, user_id, notification_id=None):
        return NotificationService.mark_read(user_id, notification_id)

    def purge_for_user(self, user_id):
        deleted, _ = Notification.objects.filter(user_id=user_id).delete()
        return deleted

    def delivery_stats(self, since=None):
        qs = DeliveryLog.objects.all()
        if since:
            qs = qs.filter(created_at__gte=since)
        return {
            "total": qs.count(),
            "sent": qs.filter(status="sent").count(),
            "failed": qs.filter(status="failed").count(),
            "suppressed": qs.filter(status="suppressed").count(),
        }

    @property
    def kinds(self):
        return list(NotificationKind.values)


service = NotificationsInterface()
