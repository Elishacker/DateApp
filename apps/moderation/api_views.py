"""Moderation REST endpoints (moderator-only)."""
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.common.mixins import ServiceResponseMixin
from apps.common.permissions import IsModerator
from apps.common.registry import services

from .serializers import ModerationDecisionSerializer, ScreenTextSerializer


class ModerationQueueAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated, IsModerator]

    def get(self, request):
        object_type = request.query_params.get("type")
        return self.ok({
            "stats": services.moderation.queue_stats(),
            "cases": services.moderation.list_pending(object_type),
        })

    def post(self, request):
        serializer = ModerationDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = services.moderation.decide(
            str(data["case_id"]), data["approved"],
            str(request.user.id), data.get("note", ""),
        )
        return self.ok(result, message="Decision recorded.")


class ScreenTextAPIView(ServiceResponseMixin, APIView):
    """Lets a client pre-check text before submitting it."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ScreenTextSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        verdict = services.moderation.screen_text(
            serializer.validated_data["text"], str(request.user.id)
        )
        # Never leak which specific rule matched to the member being screened.
        return self.ok({
            "blocked": verdict["blocked"],
            "flagged": verdict["flagged"],
            "message": verdict.get("message", ""),
        })


class TrustScoreAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated, IsModerator]

    def get(self, request, user_id):
        return self.ok(services.moderation.get_trust_score(str(user_id)))

    def post(self, request, user_id):
        banned = bool(request.data.get("shadow_banned", True))
        return self.ok(services.moderation.set_shadow_ban(str(user_id), banned))
