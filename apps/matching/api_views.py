"""Matching REST endpoints."""
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.common.mixins import ServiceResponseMixin
from apps.common.registry import services


class ScorePairAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, user_id):
        return self.ok({
            "score": services.matching.score_pair(str(request.user.id), str(user_id)),
        })


class ExplainPairAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, user_id):
        breakdown = services.matching.explain_pair(str(request.user.id), str(user_id))
        if not breakdown:
            return self.ok(message="No score available for that pair.", status=404)
        return self.ok(breakdown)


class TopScoresAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        limit = min(int(request.query_params.get("limit", 20)), 50)
        min_score = int(request.query_params.get("min_score", 0))
        rows = services.matching.top_scores_for(str(request.user.id), limit, min_score)
        refs = services.accounts.get_user_refs([r["user_id"] for r in rows])
        for row in rows:
            row["user"] = refs.get(row["user_id"])
        return self.ok({"count": len(rows), "results": rows})
