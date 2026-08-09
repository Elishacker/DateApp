"""Request context capture for the audit trail.

Stores the current request in a context variable so ``AuditService.record`` can
attach IP and user agent without every caller having to pass the request down
through the service layer.
"""
import contextvars

from apps.common.utils import client_ip, user_agent

_current_request = contextvars.ContextVar("zynora_audit_request", default=None)


def get_request_context():
    """Return ``{ip, user_agent, actor_id}`` for the in-flight request, if any."""
    request = _current_request.get()
    if request is None:
        return {}
    user = getattr(request, "user", None)
    return {
        "ip": client_ip(request),
        "user_agent": user_agent(request),
        "actor_id": str(user.id) if user is not None and user.is_authenticated else None,
        "actor_label": user.email if user is not None and user.is_authenticated else "",
    }


class AuditContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _current_request.set(request)
        try:
            return self.get_response(request)
        finally:
            _current_request.reset(token)
