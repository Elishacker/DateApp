"""Matches REST endpoints."""
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.viewsets import ViewSet

from apps.common.mixins import ServiceResponseMixin
from apps.common.permissions import IsOnboarded
from apps.common.registry import services

from .models import MatchStatus
from .services import MatchService


class MatchViewSet(ServiceResponseMixin, ViewSet):
    permission_classes = [IsAuthenticated, IsOnboarded]

    def list(self, request):
        user_id = str(request.user.id)
        status_filter = request.query_params.get("status", MatchStatus.ACTIVE)
        matches = list(MatchService.list_for_user(user_id, status_filter))
        rows = MatchService.build_match_rows(user_id, matches)
        return self.ok({
            "count": len(rows),
            "new": [r for r in rows if r["is_new"]],
            "conversations": [r for r in rows if not r["is_new"]],
        })

    def retrieve(self, request, pk=None):
        user_id = str(request.user.id)
        match = MatchService.get_for_user(pk, user_id)
        other_id = str(match.other_user_id(user_id))
        return self.ok({
            "match": services.matches.get_match(pk),
            "person": services.accounts.get_user_ref(other_id),
            "profile": services.profiles.get_public_card(other_id, viewer_id=user_id),
            "explanation": services.matching.explain_pair(user_id, other_id),
        })

    @action(detail=True, methods=["post"])
    def unmatch(self, request, pk=None):
        MatchService.unmatch(request.user, pk, request.data.get("reason", ""))
        return self.ok(message="Unmatched.")


class MatchCountView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_id = str(request.user.id)
        return self.ok({
            "active": services.matches.count_matches(user_id),
            "unread_conversations": services.chat.count_unread_conversations(user_id),
            "admirers": services.likes.count_admirers(user_id, unseen_only=True),
        })
