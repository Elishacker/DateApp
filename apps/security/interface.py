"""Public contract of the security service."""
from apps.common.interface import ModuleInterface

from .models import IPReputation, RateLimitBreach, SecurityEvent
from .services import AnomalyService, PasswordBreachService, RateLimitService, ReputationService


class SecurityInterface(ModuleInterface):
    name = "security"
    depends_on = ("authentication", "profiles", "notifications")

    def evaluate_login(self, user_id, *, ip=None, device_fingerprint="",
                       user_agent="", device_is_new=False):
        return AnomalyService.evaluate_login(
            user_id, ip=ip, device_fingerprint=device_fingerprint,
            user_agent_string=user_agent, device_is_new=device_is_new,
        )

    def record_event(self, kind, *, user_id=None, severity="low",
                     description="", metadata=None):
        event = AnomalyService.record(
            kind, user_id=user_id, severity=severity,
            description=description, metadata=metadata,
        )
        return {"event_id": str(event.id)}

    def recent_events(self, user_id, limit=20):
        return [
            {
                "id": str(e.id),
                "kind": e.kind,
                "kind_label": e.get_kind_display(),
                "severity": e.severity,
                "description": e.description,
                "risk_score": e.risk_score,
                "ip_address": e.ip_address,
                "is_resolved": e.is_resolved,
                "created_at": e.created_at.isoformat(),
            }
            for e in AnomalyService.recent_for(user_id, limit)
        ]

    def check_rate_limit(self, scope, identifier, limit, window_seconds):
        allowed, hits = RateLimitService.check(scope, identifier, limit, window_seconds)
        return {"allowed": allowed, "hits": hits}

    def is_ip_blocked(self, ip):
        return ReputationService.is_blocked(ip)

    def penalise_ip(self, ip, points, note=""):
        return ReputationService.penalise(ip, points, note)

    def is_password_breached(self, password):
        breached, count = PasswordBreachService.is_breached(password)
        return {"breached": breached, "count": count}

    def dashboard_stats(self):
        return {
            "open_events": SecurityEvent.objects.filter(is_resolved=False).count(),
            "critical": SecurityEvent.objects.filter(
                is_resolved=False, severity="critical"
            ).count(),
            "blocked_ips": IPReputation.objects.filter(is_blocked=True).count(),
            "rate_limit_breaches_24h": RateLimitBreach.objects.filter(
                created_at__gte=_yesterday()
            ).count(),
        }


def _yesterday():
    from django.utils import timezone

    return timezone.now() - timezone.timedelta(days=1)


service = SecurityInterface()
