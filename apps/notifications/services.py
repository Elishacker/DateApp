"""Notification composition, preference gating and channel dispatch."""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

from apps.common.registry import services

from .models import Channel, DeliveryLog, DeliveryStatus, Notification, NotificationKind

logger = logging.getLogger(__name__)

#: kind -> (sprite icon name, which UserSettings flag gates it)
KIND_RULES = {
    NotificationKind.MATCH: ("chat-heart-fill", "notify_on_match"),
    NotificationKind.LIKE: ("heart-fill", "notify_on_like"),
    NotificationKind.SUPER_LIKE: ("star-fill", "notify_on_like"),
    NotificationKind.MESSAGE: ("chat-dots-fill", "notify_on_message"),
    NotificationKind.PROFILE_VIEW: ("eye-fill", None),
    NotificationKind.VERIFICATION: ("patch-check-fill", None),
    NotificationKind.SUBSCRIPTION: ("gem", None),
    NotificationKind.PAYMENT: ("receipt", None),
    NotificationKind.SECURITY: ("shield-lock-fill", None),   # security alerts are never suppressed
    NotificationKind.MODERATION: ("exclamation-triangle-fill", None),
    NotificationKind.SYSTEM: ("bell-fill", None),
}

#: Alerts that ignore user preferences entirely.
ALWAYS_DELIVER = {NotificationKind.SECURITY, NotificationKind.MODERATION,
                  NotificationKind.PAYMENT}

#: Kinds that create a row in the member's notification inbox.
#:
#: The inbox is for *things other people did* — someone liked you, super liked
#: you, matched with you, messaged you. Operational records (security events,
#: receipts, verification decisions) are still delivered by email and still have
#: a home in the product, but they belong on their own pages:
#:
#:   security      -> /security/          (with full sign-in history)
#:   payment       -> /payments/history/  (with invoices)
#:   verification  -> /verification/
#:   subscription  -> /subscriptions/mine/
#:
#: Filling the inbox with those buries the notifications a member actually
#: wants to act on, which is exactly what was happening.
INBOX_KINDS = {
    NotificationKind.LIKE,
    NotificationKind.SUPER_LIKE,
    NotificationKind.MATCH,
    NotificationKind.MESSAGE,
}


class NotificationService:
    @staticmethod
    def create(user_id, kind, *, title, body="", action_url="", actor_id=None,
               object_id=None, object_type="", metadata=None, channels=None):
        """Create an inbox entry and fan out to the requested channels."""
        icon, preference_key = KIND_RULES.get(kind, ("bell-fill", None))
        prefs = services.accounts.get_notification_settings(user_id) or {}

        if kind not in ALWAYS_DELIVER and preference_key and not prefs.get(preference_key, True):
            logger.debug("suppressed %s for %s by preference", kind, user_id)
            return None

        actor_name, actor_avatar = "", ""
        if actor_id:
            ref = services.accounts.get_user_ref(actor_id) or {}
            actor_name = ref.get("display_name", "")
            actor_avatar = ref.get("avatar_url", "")

        notification = Notification.objects.create(
            user_id=user_id, kind=kind, title=title[:140], body=body[:400],
            action_url=action_url[:255], icon=icon, actor_id=actor_id,
            actor_name=actor_name, actor_avatar_url=actor_avatar,
            object_id=object_id, object_type=object_type, metadata=metadata or {},
            # Operational records are kept (support and the member's own pages
            # need them) but stay out of the inbox and its unread badge.
            in_inbox=kind in INBOX_KINDS,
        )

        if notification.in_inbox:
            NotificationService._push_in_app(notification)

        for channel in channels or []:
            NotificationService.dispatch(notification, channel, prefs)
        return notification

    @staticmethod
    def dispatch(notification, channel, prefs=None):
        prefs = prefs if prefs is not None else (
            services.accounts.get_notification_settings(notification.user_id) or {}
        )
        gate = {
            Channel.EMAIL: "email_notifications",
            Channel.PUSH: "push_notifications",
            Channel.SMS: "sms_notifications",
        }.get(channel)

        always = notification.kind in ALWAYS_DELIVER
        if gate and not always and not prefs.get(gate, True):
            DeliveryLog.objects.create(
                user_id=notification.user_id, notification=notification,
                channel=channel, status=DeliveryStatus.SUPPRESSED,
            )
            return None

        from .tasks import deliver_notification

        log = DeliveryLog.objects.create(
            user_id=notification.user_id, notification=notification, channel=channel
        )
        deliver_notification.delay(str(log.id))
        return log

    @staticmethod
    def _push_in_app(notification):
        """Live badge/toast over the member's presence socket."""
        try:
            services.chat.push_to_user(
                str(notification.user_id), "notification.new",
                {"notification": NotificationService.serialize(notification)},
            )
        except Exception:  # noqa: BLE001 - a dead socket must not fail the write
            logger.debug("in-app push skipped for %s", notification.id)

    # ---- inbox reads --------------------------------------------------------
    @staticmethod
    def list_for(user_id, unread_only=False, limit=50, kinds=None):
        qs = Notification.objects.filter(user_id=user_id, in_inbox=True)
        if kinds:
            qs = qs.filter(kind__in=list(kinds))
        if unread_only:
            qs = qs.filter(is_read=False)
        return qs[:limit]

    @staticmethod
    def unread_count(user_id):
        """Drives the navbar badge — inbox items only."""
        return Notification.objects.filter(
            user_id=user_id, in_inbox=True, is_read=False
        ).count()

    @staticmethod
    def mark_read(user_id, notification_id=None):
        qs = Notification.objects.filter(user_id=user_id, in_inbox=True, is_read=False)
        if notification_id:
            qs = qs.filter(id=notification_id)
        return qs.update(is_read=True, read_at=timezone.now())

    @staticmethod
    def delete(user_id, notification_id):
        """Remove one inbox entry. Returns the number deleted (0 or 1).

        Always scoped to the owner, so a guessed id deletes nothing. The
        delivery record survives: ``DeliveryLog.notification`` is SET_NULL, so
        tidying an inbox never destroys the audit trail of what was actually
        sent. Only inbox items can be removed this way — operational records
        are not the member's to delete.
        """
        deleted, _ = Notification.objects.filter(
            id=notification_id, user_id=user_id, in_inbox=True
        ).delete()
        return deleted

    @staticmethod
    def clear_inbox(user_id):
        """Remove every inbox entry for this member."""
        deleted, _ = Notification.objects.filter(user_id=user_id, in_inbox=True).delete()
        return deleted

    @staticmethod
    def serialize(notification):
        """Render-ready shape; the template prints these fields verbatim."""
        return {
            "id": str(notification.id),
            "kind": notification.kind,
            "icon": notification.icon,
            "title": notification.title,
            "body": notification.body,
            "action_url": notification.action_url,
            "actor_name": notification.actor_name,
            "actor_avatar_url": notification.actor_avatar_url,
            "is_read": notification.is_read,
            "created_at": notification.created_at.isoformat(),
            "time_label": _relative(notification.created_at),
        }


class NotDeliverable(Exception):
    """No route to the member on this channel.

    Distinct from a delivery *failure*: there is nothing to retry, so the worker
    marks the log suppressed instead of burning attempts on it.
    """


class EmailChannel:
    @staticmethod
    def send(log):
        contact = services.accounts.get_contact_channels(log.user_id) or {}
        address = contact.get("email")
        if not address:
            raise NotDeliverable("No email address on file.")

        template = log.template or "generic"
        context = {
            "name": contact.get("name", ""),
            "title": log.subject or (log.notification.title if log.notification else ""),
            "body": log.notification.body if log.notification else "",
            "action_url": log.notification.action_url if log.notification else "",
            "site": settings.ZYNORA,
            **(log.notification.metadata if log.notification else {}),
            **(log.context or {}),
        }

        subject = log.subject or context["title"] or "Zynora"
        text_body = render_to_string(f"emails/{template}.txt", context)
        try:
            html_body = render_to_string(f"emails/{template}.html", context)
        except Exception:  # noqa: BLE001 - HTML part is optional
            html_body = None

        message = EmailMultiAlternatives(
            subject=subject, body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL, to=[address],
        )
        if html_body:
            message.attach_alternative(html_body, "text/html")
        message.send(fail_silently=False)

        log.destination = address
        log.save(update_fields=["destination"])
        return f"email:{address}"


class PushChannel:
    """Token fan-out. Wire a real provider (FCM/APNs) into ``_deliver``."""

    @staticmethod
    def send(log):
        tokens = services.accounts.get_push_tokens(log.user_id)
        if not tokens:
            raise NotDeliverable("No push tokens registered.")
        payload = {
            "title": log.notification.title if log.notification else "Zynora",
            "body": log.notification.body if log.notification else "",
            "url": log.notification.action_url if log.notification else "",
        }
        PushChannel._deliver(tokens, payload)
        log.destination = f"{len(tokens)} device(s)"
        log.save(update_fields=["destination"])
        return f"push:{len(tokens)}"

    @staticmethod
    def _deliver(tokens, payload):
        # Integration point: swap for firebase-admin or an HTTP call to FCM.
        logger.info("push (stub) to %d device(s): %s", len(tokens), payload["title"])


class SMSChannel:
    """Integration point for Twilio / Africa's Talking / Beem."""

    @staticmethod
    def send(log):
        contact = services.accounts.get_contact_channels(log.user_id) or {}
        phone = contact.get("phone")
        if not phone:
            raise NotDeliverable("No phone number on file.")
        text = (log.notification.title if log.notification else "")[:160]
        logger.info("sms (stub) to %s: %s", phone, text)
        log.destination = phone
        log.save(update_fields=["destination"])
        return f"sms:{phone}"


CHANNEL_HANDLERS = {
    Channel.EMAIL: EmailChannel.send,
    Channel.PUSH: PushChannel.send,
    Channel.SMS: SMSChannel.send,
}


def _relative(moment):
    from apps.common.utils import humanize_delta

    return humanize_delta(moment)
