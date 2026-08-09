"""In-process event bus — the asynchronous half of the service contract.

Modules must not call each other to *announce* things; they publish an event and
move on. Today the bus dispatches in-process (optionally handing off to Celery).
When a module is extracted into its own deployment, only :func:`publish` changes:
point it at RabbitMQ/Kafka and every producer and consumer keeps working.

Rules for handlers:
  * they must never raise into the producer — failures are logged, not bubbled;
  * they receive a plain JSON-serialisable dict, never an ORM instance;
  * ordering between handlers is not guaranteed.
"""
import logging
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone as dt_timezone

logger = logging.getLogger("zynora.events")

_HANDLERS = defaultdict(list)


class Event:
    """Canonical event names. ``<module>.<aggregate>.<past-tense-verb>``."""

    # accounts
    USER_REGISTERED = "accounts.user.registered"
    USER_ACTIVATED = "accounts.user.activated"
    USER_DEACTIVATED = "accounts.user.deactivated"
    USER_BANNED = "accounts.user.banned"
    USER_DELETED = "accounts.user.deleted"
    USER_BLOCKED = "accounts.user.blocked"
    ROLE_CHANGED = "accounts.role.changed"

    # authentication
    LOGIN_SUCCEEDED = "authentication.login.succeeded"
    LOGIN_FAILED = "authentication.login.failed"
    LOGOUT = "authentication.session.ended"
    PASSWORD_CHANGED = "authentication.password.changed"
    PASSWORD_RESET_REQUESTED = "authentication.password.reset_requested"
    EMAIL_VERIFIED = "authentication.email.verified"
    MFA_ENABLED = "authentication.mfa.enabled"
    MFA_DISABLED = "authentication.mfa.disabled"

    # profiles / onboarding
    PROFILE_UPDATED = "profiles.profile.updated"
    PHOTO_UPLOADED = "profiles.photo.uploaded"
    PREFERENCES_UPDATED = "profiles.preferences.updated"
    ONBOARDING_COMPLETED = "onboarding.wizard.completed"

    # engagement
    LIKE_SENT = "likes.like.sent"
    SUPER_LIKE_SENT = "likes.super_like.sent"
    PASS_SENT = "likes.pass.sent"
    MATCH_CREATED = "matches.match.created"
    MATCH_ENDED = "matches.match.ended"

    # chat
    MESSAGE_SENT = "chat.message.sent"
    MESSAGE_READ = "chat.message.read"
    CONVERSATION_STARTED = "chat.conversation.started"

    # money
    SUBSCRIPTION_STARTED = "subscriptions.subscription.started"
    SUBSCRIPTION_RENEWED = "subscriptions.subscription.renewed"
    SUBSCRIPTION_CANCELLED = "subscriptions.subscription.cancelled"
    SUBSCRIPTION_EXPIRED = "subscriptions.subscription.expired"
    PAYMENT_INITIATED = "payments.payment.initiated"
    PAYMENT_SUCCEEDED = "payments.payment.succeeded"
    PAYMENT_FAILED = "payments.payment.failed"
    REFUND_ISSUED = "payments.refund.issued"

    # trust & safety
    VERIFICATION_SUBMITTED = "verification.request.submitted"
    VERIFICATION_APPROVED = "verification.request.approved"
    VERIFICATION_REJECTED = "verification.request.rejected"
    CONTENT_FLAGGED = "moderation.content.flagged"
    USER_REPORTED = "reports.report.created"
    SECURITY_ANOMALY = "security.anomaly.detected"


@dataclass
class EventEnvelope:
    """What a handler receives. Mirrors a broker message one-for-one."""

    name: str
    payload: dict
    actor_id: str | None = None
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    occurred_at: str = field(
        default_factory=lambda: datetime.now(dt_timezone.utc).isoformat()
    )

    def to_dict(self):
        return asdict(self)


def subscribe(event_name, handler=None):
    """Register a handler. Usable directly or as a decorator."""

    def _register(func):
        if func not in _HANDLERS[event_name]:
            _HANDLERS[event_name].append(func)
        return func

    return _register(handler) if handler else _register


def unsubscribe(event_name, handler):
    if handler in _HANDLERS[event_name]:
        _HANDLERS[event_name].remove(handler)


def publish(name, payload=None, actor_id=None):
    """Emit an event. Never raises — a broken subscriber cannot break a sale."""
    envelope = EventEnvelope(name=name, payload=payload or {}, actor_id=str(actor_id) if actor_id else None)
    handlers = _HANDLERS.get(name, [])
    logger.debug("event %s -> %d handler(s)", name, len(handlers))

    for handler in handlers:
        try:
            handler(envelope)
        except Exception:  # noqa: BLE001 - isolation is the whole point
            logger.exception("Event handler %s failed for %s", getattr(handler, "__name__", handler), name)
    return envelope


def registered_handlers():
    """Introspection used by ``manage.py service_map``."""
    return {name: [h.__module__ + "." + h.__name__ for h in handlers]
            for name, handlers in _HANDLERS.items() if handlers}
