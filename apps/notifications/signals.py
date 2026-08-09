"""Notification rules.

This is the entire "who gets told about what" policy for the platform, in one
readable place. Every rule is a reaction to an event — notifications never
reaches into another module to find out that something happened.
"""
import logging

from apps.common.events import Event, subscribe
from apps.common.registry import services

from .models import Channel, NotificationKind
from .services import NotificationService

logger = logging.getLogger(__name__)


@subscribe(Event.USER_REGISTERED)
def welcome(envelope):
    payload = envelope.payload
    NotificationService.create(
        payload["user_id"], NotificationKind.SYSTEM,
        title="Welcome to Zynora",
        body="Finish your profile to start meeting people.",
        action_url="/onboarding/",
        channels=[Channel.EMAIL],
    )


@subscribe(Event.MATCH_CREATED)
def new_match(envelope):
    payload = envelope.payload
    pairs = ((payload["user_a"], payload["user_b"]), (payload["user_b"], payload["user_a"]))
    for recipient, other in pairs:
        ref = services.accounts.get_user_ref(other) or {}
        NotificationService.create(
            recipient, NotificationKind.MATCH,
            title="It's a match!",
            body=f"You and {ref.get('display_name', 'someone')} liked each other.",
            action_url=f"/matches/{payload['match_id']}/",
            actor_id=other, object_id=payload["match_id"], object_type="match",
            channels=[Channel.PUSH],
        )


@subscribe(Event.LIKE_SENT)
def new_like(envelope):
    payload = envelope.payload
    # Free accounts get the count, not the identity — that is the upsell.
    unlocked = services.subscriptions.has_entitlement(
        payload["receiver_id"], "see_who_likes_you"
    )
    ref = services.accounts.get_user_ref(payload["sender_id"]) or {}
    NotificationService.create(
        payload["receiver_id"], NotificationKind.LIKE,
        title="Someone likes you",
        body=(f"{ref.get('display_name', 'Someone')} liked your profile."
              if unlocked else "Upgrade to see who it was."),
        action_url="/discover/admirers/",
        actor_id=payload["sender_id"] if unlocked else None,
        channels=[Channel.PUSH],
    )


@subscribe(Event.SUPER_LIKE_SENT)
def new_super_like(envelope):
    payload = envelope.payload
    ref = services.accounts.get_user_ref(payload["sender_id"]) or {}
    NotificationService.create(
        payload["receiver_id"], NotificationKind.SUPER_LIKE,
        title="You got a Super Like!",
        body=payload.get("message") or f"{ref.get('display_name', 'Someone')} super liked you.",
        action_url="/discover/admirers/",
        actor_id=payload["sender_id"],
        channels=[Channel.PUSH],
    )


@subscribe(Event.MESSAGE_SENT)
def new_message(envelope):
    payload = envelope.payload
    if payload.get("is_muted"):
        return
    ref = services.accounts.get_user_ref(payload["sender_id"]) or {}
    NotificationService.create(
        payload["receiver_id"], NotificationKind.MESSAGE,
        title=f"Message from {ref.get('display_name', 'your match')}",
        body=payload.get("preview", ""),
        action_url=f"/chat/{payload['conversation_id']}/",
        actor_id=payload["sender_id"],
        object_id=payload.get("message_id"), object_type="message",
        channels=[Channel.PUSH],
    )


@subscribe(Event.VERIFICATION_APPROVED)
def verification_approved(envelope):
    payload = envelope.payload
    NotificationService.create(
        payload["user_id"], NotificationKind.VERIFICATION,
        title="You're verified",
        body=f"Your {payload.get('kind', 'identity')} verification was approved.",
        action_url="/verification/",
        channels=[Channel.EMAIL],
    )


@subscribe(Event.VERIFICATION_REJECTED)
def verification_rejected(envelope):
    payload = envelope.payload
    NotificationService.create(
        payload["user_id"], NotificationKind.VERIFICATION,
        title="Verification needs another look",
        body=payload.get("reason", "Please submit a clearer photo."),
        action_url="/verification/",
        channels=[Channel.EMAIL],
    )


@subscribe(Event.SUBSCRIPTION_STARTED)
def subscription_started(envelope):
    payload = envelope.payload
    NotificationService.create(
        payload["user_id"], NotificationKind.SUBSCRIPTION,
        title=f"Welcome to Zynora {payload.get('plan_name', 'Premium')}",
        body="Your new features are active.",
        action_url="/subscriptions/",
        channels=[Channel.EMAIL],
    )


@subscribe(Event.SUBSCRIPTION_EXPIRED)
def subscription_expired(envelope):
    payload = envelope.payload
    NotificationService.create(
        payload["user_id"], NotificationKind.SUBSCRIPTION,
        title="Your plan has ended",
        body="Renew to keep unlimited likes and see who likes you.",
        action_url="/subscriptions/",
        channels=[Channel.EMAIL],
    )


@subscribe(Event.PAYMENT_SUCCEEDED)
def payment_succeeded(envelope):
    payload = envelope.payload
    NotificationService.create(
        payload["user_id"], NotificationKind.PAYMENT,
        title="Payment received",
        body=f"{payload.get('currency', '')} {payload.get('amount', '')} — thank you.",
        action_url="/payments/history/",
        metadata={"reference": payload.get("reference", "")},
        channels=[Channel.EMAIL],
    )


@subscribe(Event.PAYMENT_FAILED)
def payment_failed(envelope):
    payload = envelope.payload
    NotificationService.create(
        payload["user_id"], NotificationKind.PAYMENT,
        title="Payment failed",
        body=payload.get("reason", "We couldn't process your payment."),
        action_url="/payments/",
        channels=[Channel.EMAIL],
    )


@subscribe(Event.SECURITY_ANOMALY)
def security_alert(envelope):
    payload = envelope.payload
    if not payload.get("user_id"):
        return
    NotificationService.create(
        payload["user_id"], NotificationKind.SECURITY,
        title="Unusual sign-in detected",
        body=payload.get("description", "We noticed a sign-in that didn't look like you."),
        action_url="/auth/security/",
        metadata={"ip": payload.get("ip", ""), "severity": payload.get("severity", "")},
        channels=[Channel.EMAIL, Channel.PUSH],
    )


@subscribe(Event.LOGIN_SUCCEEDED)
def new_device_alert(envelope):
    payload = envelope.payload
    if not payload.get("device_is_new"):
        return
    NotificationService.create(
        payload["user_id"], NotificationKind.SECURITY,
        title="New device signed in",
        body="If this wasn't you, secure your account now.",
        action_url="/account/devices/",
        metadata={"ip": payload.get("ip", "")},
        channels=[Channel.EMAIL],
    )


@subscribe(Event.CONTENT_FLAGGED)
def content_flagged(envelope):
    payload = envelope.payload
    if payload.get("approved", True) or not payload.get("owner_id"):
        return
    NotificationService.create(
        payload["owner_id"], NotificationKind.MODERATION,
        title="Content removed",
        body=payload.get("reason", "Something you uploaded didn't meet our guidelines."),
        action_url="/profile/photos/",
        channels=[Channel.EMAIL],
    )
