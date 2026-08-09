"""Recommendation REST endpoints."""
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.common.mixins import ServiceResponseMixin
from apps.common.permissions import IsOnboarded
from apps.common.registry import services


class RecommendationSetAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated, IsOnboarded]

    def get(self, request, set_name="top_picks"):
        limit = min(int(request.query_params.get("limit", 10)), 30)
        return self.ok({
            "set": set_name,
            "cards": services.recommendation.get_set(str(request.user.id), set_name, limit),
        })


class AllRecommendationsAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated, IsOnboarded]

    def get(self, request):
        sets = services.recommendation.get_all_sets(str(request.user.id))
        return self.ok({"sets": [s for s in sets if s["cards"]]})

    def post(self, request):
        """Force a rebuild."""
        count = services.recommendation.rebuild(str(request.user.id))
        return self.ok({"generated": count}, message="Recommendations refreshed.")
