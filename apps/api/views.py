"""Gateway-level endpoints: discovery of the API, health, and a home screen."""
from django.urls import reverse
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView

from apps.common.mixins import ServiceResponseMixin
from apps.common.registry import ServiceRegistry, services


class APIRootView(ServiceResponseMixin, APIView):
    """Self-describing index of the v1 surface."""

    permission_classes = [AllowAny]

    MOUNTS = {
        "authentication": "auth/", "accounts": "accounts/", "profiles": "profiles/",
        "onboarding": "onboarding/", "discovery": "discovery/", "likes": "likes/",
        "matches": "matches/", "matching": "matching/",
        "recommendation": "recommendations/", "chat": "chat/",
        "notifications": "notifications/", "subscriptions": "subscriptions/",
        "payments": "payments/", "verification": "verification/",
        "moderation": "moderation/", "reports": "reports/", "analytics": "analytics/",
    }

    def get(self, request):
        base = request.build_absolute_uri("/api/v1/")
        return self.ok({
            "version": "v1",
            "services": {
                name: f"{base}{mount}" for name, mount in sorted(self.MOUNTS.items())
            },
            "websockets": {
                "chat": "/ws/chat/<conversation_id>/?token=<jwt>",
                "presence": "/ws/presence/?token=<jwt>",
            },
            "docs": f"{base}health/",
        })


class APIHealthView(ServiceResponseMixin, APIView):
    """Per-service readiness, useful behind a load balancer."""

    permission_classes = [AllowAny]

    def get(self, request):
        from django.db import connection

        checks = {}
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            checks["database"] = "ok"
        except Exception as exc:  # noqa: BLE001
            checks["database"] = f"error: {exc}"

        module_status = {}
        for name in ServiceRegistry.LOCAL_MODULES:
            try:
                services.resolve(name).describe()
                module_status[name] = "ok"
            except Exception as exc:  # noqa: BLE001
                module_status[name] = f"error: {exc}"

        healthy = checks["database"] == "ok" and all(
            v == "ok" for v in module_status.values()
        )
        return self.ok(
            {"status": "healthy" if healthy else "degraded",
             "checks": checks, "services": module_status},
            status=200 if healthy else 503,
        )


class MeSummaryView(ServiceResponseMixin, APIView):
    """One call that gives a mobile client everything the home screen needs.

    This is the gateway earning its keep: seven services fanned out here rather
    than seven round trips from the handset.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_id = str(request.user.id)
        return self.ok({
            "user": services.accounts.get_user_ref(user_id),
            "account": services.accounts.get_account_state(user_id),
            "profile_completion": services.profiles.get_completion(user_id),
            "onboarding": services.onboarding.get_state(user_id),
            "subscription": services.subscriptions.get_summary(user_id),
            "quota": services.likes.get_quota(user_id),
            "verification": services.verification.get_status(user_id),
            "badges": {
                "notifications": services.notifications.get_unread_count(user_id),
                "messages": services.chat.count_unread_conversations(user_id),
                "matches": services.matches.count_matches(user_id),
                "admirers": services.likes.count_admirers(user_id, unseen_only=True),
            },
        })
