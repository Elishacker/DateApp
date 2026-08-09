"""Public contract of the matches service."""
from django.db.models import Q

from apps.common.interface import ModuleInterface

from .models import Match, MatchStatus
from .services import MatchService


class MatchesInterface(ModuleInterface):
    name = "matches"
    depends_on = ("accounts", "matching", "chat")

    def create_match(self, user_a, user_b, origin="mutual_like"):
        match = MatchService.create(user_a, user_b, origin)
        return self._serialize(match)

    def are_matched(self, user_a, user_b):
        return MatchService.are_matched(user_a, user_b)

    def get_match(self, match_id):
        match = Match.objects.filter(id=match_id).first()
        return self._serialize(match) if match else None

    def get_match_between(self, user_a, user_b):
        match = MatchService.find(user_a, user_b)
        return self._serialize(match) if match else None

    def get_participants(self, match_id):
        """Chat calls this to authorise a conversation."""
        match = Match.objects.filter(id=match_id).first()
        if not match:
            return None
        return {
            "match_id": str(match.id),
            "participants": [str(match.user_low_id), str(match.user_high_id)],
            "is_active": match.is_active,
        }

    def list_match_ids(self, user_id, status="active"):
        qs = Match.objects.filter(Q(user_low_id=user_id) | Q(user_high_id=user_id))
        if status:
            qs = qs.filter(status=status)
        return [str(pk) for pk in qs.values_list("id", flat=True)]

    def get_matched_user_ids(self, user_id):
        """Discovery excludes people you are already matched with."""
        ids = []
        for match in Match.objects.filter(
            Q(user_low_id=user_id) | Q(user_high_id=user_id)
        ).only("user_low_id", "user_high_id"):
            ids.append(str(match.other_user_id(user_id)))
        return ids

    def count_matches(self, user_id, status="active"):
        qs = Match.objects.filter(Q(user_low_id=user_id) | Q(user_high_id=user_id))
        if status:
            qs = qs.filter(status=status)
        return qs.count()

    def touch(self, match_id, message_count_delta=0):
        return MatchService.touch(match_id, message_count_delta)

    def end_between(self, user_a, user_b, reason="blocked"):
        return MatchService.end_all_for_pair(user_a, user_b, reason)

    def end_all_for_user(self, user_id, reason="account closed"):
        return MatchService.end_all_for_user(user_id, reason)

    def daily_stats(self, since=None):
        qs = Match.objects.all()
        if since:
            qs = qs.filter(matched_at__gte=since)
        total = qs.count()
        conversing = qs.filter(has_conversation=True).count()
        return {
            "matches": total,
            "with_conversation": conversing,
            "conversation_rate": round(conversing / total * 100, 1) if total else 0.0,
            "active": Match.objects.filter(status=MatchStatus.ACTIVE).count(),
        }

    @staticmethod
    def _serialize(match):
        return {
            "id": str(match.id),
            "user_low": str(match.user_low_id),
            "user_high": str(match.user_high_id),
            "status": match.status,
            "origin": match.origin,
            "compatibility_score": match.compatibility_score,
            "matched_at": match.matched_at.isoformat(),
            "last_interaction_at": (
                match.last_interaction_at.isoformat() if match.last_interaction_at else None
            ),
            "has_conversation": match.has_conversation,
            "message_count": match.message_count,
            "is_active": match.is_active,
        }


service = MatchesInterface()
