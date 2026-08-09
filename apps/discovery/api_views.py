"""Discovery REST endpoints."""
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.common.mixins import ServiceResponseMixin
from apps.common.permissions import IsOnboarded
from apps.common.registry import services


class FeedAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated, IsOnboarded]

    FEEDS = {
        "for-you": "get_feed",
        "nearby": "get_nearby",
        "online": "get_online",
        "new": "get_newest",
        "verified": "get_verified",
    }

    def get(self, request):
        tab = request.query_params.get("tab", "for-you")
        method = self.FEEDS.get(tab, "get_feed")
        limit = min(int(request.query_params.get("limit", 20)), 50)
        refresh = request.query_params.get("refresh") == "true"

        kwargs = {"limit": limit}
        if method == "get_feed":
            kwargs["refresh"] = refresh

        cards = getattr(services.discovery, method)(str(request.user.id), **kwargs)
        return self.ok({
            "tab": tab,
            "count": len(cards),
            "cards": cards,
            "quota": services.likes.get_quota(str(request.user.id)),
        })


class AdmirersAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated, IsOnboarded]

    def get(self, request):
        user_id = str(request.user.id)
        unlocked = services.subscriptions.has_entitlement(user_id, "see_who_likes_you")
        total = services.likes.count_admirers(user_id)
        if not unlocked:
            return self.ok(
                {"total": total, "cards": [], "locked": True},
                message="Upgrade to see who likes you.",
            )
        cards = services.discovery.get_admirers(user_id)
        services.likes.mark_admirers_seen(user_id)
        return self.ok({"total": total, "cards": cards, "locked": False})
