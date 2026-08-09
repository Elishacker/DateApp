"""The audit trail is written entirely from events.

Because every consequential action already publishes an event, audit needs no
hooks inside other modules — it just listens. Adding a new audited action means
adding a row to ``EVENT_MAP``, nothing else.
"""
from apps.common.events import Event, subscribe

from .middleware import get_request_context
from .models import AuditCategory
from .services import AuditService

#: event name -> (action, category, description template, sensitive)
EVENT_MAP = {
    Event.USER_REGISTERED: ("user.registered", AuditCategory.ACCOUNT,
                            "New account created", False),
    Event.USER_ACTIVATED: ("user.activated", AuditCategory.ACCOUNT,
                           "Account activated", False),
    Event.USER_DEACTIVATED: ("user.deactivated", AuditCategory.ACCOUNT,
                             "Account deactivated", False),
    Event.USER_BANNED: ("user.banned", AuditCategory.SAFETY,
                        "Account suspended or banned", False),
    Event.USER_DELETED: ("user.deleted", AuditCategory.ACCOUNT,
                         "Account deletion", False),
    Event.ROLE_CHANGED: ("accounts.role.changed", AuditCategory.ADMIN,
                         "Staff role changed", False),
    Event.LOGIN_SUCCEEDED: ("auth.login", AuditCategory.AUTHENTICATION,
                            "Signed in", False),
    Event.LOGOUT: ("auth.logout", AuditCategory.AUTHENTICATION, "Signed out", False),
    Event.PASSWORD_CHANGED: ("auth.password_changed", AuditCategory.AUTHENTICATION,
                             "Password changed", True),
    Event.PASSWORD_RESET_REQUESTED: ("auth.password_reset_requested",
                                     AuditCategory.AUTHENTICATION,
                                     "Password reset requested", True),
    Event.EMAIL_VERIFIED: ("auth.email_verified", AuditCategory.AUTHENTICATION,
                           "Email address verified", False),
    Event.MFA_ENABLED: ("auth.mfa_enabled", AuditCategory.SECURITY,
                        "Two-factor authentication enabled", True),
    Event.MFA_DISABLED: ("auth.mfa_disabled", AuditCategory.SECURITY,
                         "Two-factor authentication disabled", True),
    Event.PROFILE_UPDATED: ("profile.updated", AuditCategory.PROFILE,
                            "Profile updated", False),
    Event.ONBOARDING_COMPLETED: ("onboarding.completed", AuditCategory.ACCOUNT,
                                 "Onboarding completed", False),
    Event.MATCH_CREATED: ("match.created", AuditCategory.ENGAGEMENT,
                          "New match", False),
    Event.MATCH_ENDED: ("match.ended", AuditCategory.ENGAGEMENT,
                        "Match ended", False),
    Event.SUBSCRIPTION_STARTED: ("subscription.started", AuditCategory.BILLING,
                                 "Subscription started", False),
    Event.SUBSCRIPTION_RENEWED: ("subscription.renewed", AuditCategory.BILLING,
                                 "Subscription renewed", False),
    Event.SUBSCRIPTION_CANCELLED: ("subscription.cancelled", AuditCategory.BILLING,
                                   "Subscription cancelled", False),
    Event.PAYMENT_INITIATED: ("payment.initiated", AuditCategory.BILLING,
                              "Payment started", False),
    Event.PAYMENT_SUCCEEDED: ("payment.succeeded", AuditCategory.BILLING,
                              "Payment completed", False),
    Event.PAYMENT_FAILED: ("payment.failed", AuditCategory.BILLING,
                           "Payment failed", False),
    Event.REFUND_ISSUED: ("payment.refunded", AuditCategory.BILLING,
                          "Refund issued", False),
    Event.VERIFICATION_SUBMITTED: ("verification.submitted", AuditCategory.SAFETY,
                                   "Verification submitted", True),
    Event.VERIFICATION_APPROVED: ("verification.approved", AuditCategory.SAFETY,
                                  "Verification approved", False),
    Event.VERIFICATION_REJECTED: ("verification.rejected", AuditCategory.SAFETY,
                                  "Verification rejected", False),
    Event.USER_REPORTED: ("report.created", AuditCategory.SAFETY,
                          "Member reported", False),
    Event.USER_BLOCKED: ("user.blocked", AuditCategory.SAFETY,
                         "Member blocked", False),
    Event.CONTENT_FLAGGED: ("moderation.decision", AuditCategory.SAFETY,
                            "Moderation decision", False),
    Event.SECURITY_ANOMALY: ("security.anomaly", AuditCategory.SECURITY,
                             "Security anomaly detected", False),
}


def _handler(event_name, action, category, description, sensitive):
    def handle(envelope):
        payload = envelope.payload
        context = get_request_context()

        AuditService.record(
            action,
            actor_id=envelope.actor_id or context.get("actor_id"),
            actor_label=context.get("actor_label", ""),
            category=category,
            description=description,
            object_type=_object_type(payload),
            object_id=_object_id(payload),
            target_user_id=payload.get("target_user_id") or payload.get("user_id"),
            ip=payload.get("ip") or context.get("ip"),
            user_agent=context.get("user_agent", ""),
            metadata=payload,
            sensitive=sensitive,
        )

    handle.__name__ = f"audit_{action.replace('.', '_')}"
    return handle


def _object_type(payload):
    for key, label in (
        ("match_id", "match"), ("payment_id", "payment"),
        ("subscription_id", "subscription"), ("report_id", "report"),
        ("case_id", "moderation_case"), ("request_id", "verification_request"),
        ("message_id", "message"), ("event_id", "security_event"),
    ):
        if payload.get(key):
            return label
    return "user"


def _object_id(payload):
    for key in ("match_id", "payment_id", "subscription_id", "report_id",
                "case_id", "request_id", "message_id", "event_id", "user_id"):
        if payload.get(key):
            return payload[key]
    return ""


# Register one handler per mapped event.
for _event_name, (_action, _category, _description, _sensitive) in EVENT_MAP.items():
    subscribe(_event_name, _handler(_event_name, _action, _category,
                                    _description, _sensitive))
