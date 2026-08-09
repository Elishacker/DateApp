"""Security console for members and staff."""
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from apps.common.constants import Capability
from apps.common.mixins import CapabilityRequiredMixin
from apps.common.registry import services

from .models import IPReputation, RateLimitBreach
from .services import AnomalyService

SEVERITY_TONE = {
    "critical": "danger", "high": "danger", "medium": "warning",
    "low": "muted", "info": "muted",
}


class MySecurityView(LoginRequiredMixin, TemplateView):
    """What the member themselves can see about their account security."""

    template_name = "security/my_security.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user_id = str(self.request.user.id)

        events = services.security.recent_events(user_id, limit=20)
        for event in events:
            event["tone"] = SEVERITY_TONE.get(event["severity"], "muted")

        context["events"] = events
        context["has_events"] = bool(events)
        context["sessions"] = services.authentication.list_active_sessions(user_id)
        context["mfa"] = services.authentication.mfa_status(user_id)
        context["attempts"] = services.authentication.recent_login_attempts(user_id, 10)
        context["checklist"] = self._checklist(user_id)
        return context

    def _checklist(self, user_id):
        mfa = services.authentication.mfa_status(user_id)
        verification = services.verification.get_status(user_id)
        return [
            {"label": "Verify your email", "done": self.request.user.is_email_verified,
             "url": "/auth/verify-email/"},
            {"label": "Turn on two-factor authentication", "done": mfa["confirmed"],
             "url": "/auth/mfa/setup/"},
            {"label": "Verify your phone number", "done": verification["level"] >= 2,
             "url": "/verification/phone/"},
            {"label": "Verify your photo", "done": verification["level"] >= 3,
             "url": "/verification/selfie/"},
            {"label": "Review your signed-in devices", "done": False,
             "url": "/account/devices/"},
        ]


class SecurityDashboardView(CapabilityRequiredMixin, TemplateView):
    """Platform-wide security posture, staff only."""
    required_capability = Capability.VIEW_SECURITY_OPS

    template_name = "security/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        events = AnomalyService.open_events(limit=100)
        user_ids = [str(e.user_id) for e in events if e.user_id]
        refs = services.accounts.get_user_refs(user_ids)

        context["stats"] = services.security.dashboard_stats()
        context["events"] = [
            {
                "id": str(e.id),
                "user": refs.get(str(e.user_id)) if e.user_id else None,
                "kind_label": e.get_kind_display(),
                "severity": e.severity,
                "tone": SEVERITY_TONE.get(e.severity, "muted"),
                "description": e.description,
                "risk_score": e.risk_score,
                "ip_address": e.ip_address,
                "created_at": e.created_at,
            }
            for e in events
        ]
        context["blocked_ips"] = [
            {"ip": r.ip_address, "score": r.score, "failed_logins": r.failed_logins,
             "blocked_until": r.blocked_until, "notes": r.notes}
            for r in IPReputation.objects.filter(is_blocked=True)[:50]
        ]
        context["recent_breaches"] = [
            {"scope": b.scope, "identifier": b.identifier, "path": b.path,
             "hits": b.hits, "created_at": b.created_at}
            for b in RateLimitBreach.objects.all()[:50]
        ]
        return context
