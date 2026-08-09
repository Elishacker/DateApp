"""Match lifecycle."""
import logging

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.common.events import Event, publish
from apps.common.exceptions import NotFound, PermissionDenied
from apps.common.registry import services

from .models import Match, MatchOrigin, MatchStatus

logger = logging.getLogger(__name__)


class MatchService:
    @staticmethod
    @transaction.atomic
    def create(user_a, user_b, origin=MatchOrigin.MUTUAL_LIKE):
        low, high = Match.order_pair(user_a, user_b)
        match, created = Match.objects.get_or_create(
            user_low_id=low, user_high_id=high,
            defaults={
                "origin": origin,
                "compatibility_score": services.matching.score_pair(str(low), str(high)) or 0,
            },
        )
        if not created and match.status != MatchStatus.ACTIVE:
            # A previously ended match is revived rather than duplicated.
            match.status = MatchStatus.ACTIVE
            match.matched_at = timezone.now()
            match.ended_at = None
            match.ended_by = None
            match.end_reason = ""
            match.save(update_fields=["status", "matched_at", "ended_at",
                                      "ended_by", "end_reason", "updated_at"])
            created = True

        if created:
            publish(Event.MATCH_CREATED, {
                "match_id": str(match.id),
                "user_a": str(low),
                "user_b": str(high),
                "origin": origin,
                "compatibility_score": match.compatibility_score,
            }, actor_id=user_a)
            logger.info("match created %s", match.id)
        return match

    @staticmethod
    def get_for_user(match_id, user_id):
        match = Match.objects.filter(id=match_id).first()
        if not match:
            raise NotFound("Match not found.")
        if not match.involves(user_id):
            raise PermissionDenied("This match is not yours.")
        return match

    @staticmethod
    def are_matched(user_a, user_b):
        low, high = Match.order_pair(user_a, user_b)
        return Match.objects.filter(
            user_low_id=low, user_high_id=high, status=MatchStatus.ACTIVE
        ).exists()

    @staticmethod
    def find(user_a, user_b):
        low, high = Match.order_pair(user_a, user_b)
        return Match.objects.filter(user_low_id=low, user_high_id=high).first()

    @staticmethod
    def list_for_user(user_id, status=MatchStatus.ACTIVE):
        qs = Match.objects.filter(Q(user_low_id=user_id) | Q(user_high_id=user_id))
        if status:
            qs = qs.filter(status=status)
        return qs.order_by("-last_interaction_at", "-matched_at")

    @staticmethod
    @transaction.atomic
    def unmatch(user, match_id, reason=""):
        match = MatchService.get_for_user(match_id, user.id)
        other_id = str(match.other_user_id(user.id))
        match.end(by_user_id=user.id, reason=reason)
        publish(Event.MATCH_ENDED, {
            "match_id": str(match.id),
            "ended_by": str(user.id),
            "other_user_id": other_id,
            "reason": reason,
        }, actor_id=user.id)
        return match

    @staticmethod
    def end_all_for_pair(user_a, user_b, reason="blocked"):
        """Used when one member blocks the other."""
        low, high = Match.order_pair(user_a, user_b)
        matches = Match.objects.filter(
            user_low_id=low, user_high_id=high, status=MatchStatus.ACTIVE
        )
        for match in matches:
            match.end(by_user_id=user_a, reason=reason, status=MatchStatus.BLOCKED)
            publish(Event.MATCH_ENDED, {
                "match_id": str(match.id), "ended_by": str(user_a),
                "other_user_id": str(user_b), "reason": reason,
            }, actor_id=user_a)
        return matches.count()

    @staticmethod
    def end_all_for_user(user_id, reason="account closed"):
        matches = Match.objects.filter(
            Q(user_low_id=user_id) | Q(user_high_id=user_id), status=MatchStatus.ACTIVE
        )
        count = 0
        for match in matches:
            match.end(by_user_id=user_id, reason=reason)
            count += 1
        return count

    @staticmethod
    def touch(match_id, message_count_delta=0):
        """Called when a message is sent, to keep the match list ordered."""
        updates = {"last_interaction_at": timezone.now(), "has_conversation": True}
        match = Match.objects.filter(id=match_id).first()
        if not match:
            return False
        match.last_interaction_at = updates["last_interaction_at"]
        match.has_conversation = True
        if message_count_delta:
            match.message_count += message_count_delta
        match.save(update_fields=["last_interaction_at", "has_conversation",
                                  "message_count", "updated_at"])
        return True

    # ---- presentation helpers (used by the view, never the template) --------
    @staticmethod
    def build_match_rows(user_id, matches):
        """Assemble render-ready rows by fanning out to the other services once."""
        other_ids = [str(m.other_user_id(user_id)) for m in matches]
        refs = services.accounts.get_user_refs(other_ids)
        previews = services.chat.get_conversation_previews(str(user_id), other_ids)

        rows = []
        for match in matches:
            other_id = str(match.other_user_id(user_id))
            ref = refs.get(other_id)
            if not ref:
                continue
            preview = previews.get(other_id, {})
            rows.append({
                "match_id": str(match.id),
                "user": ref,
                "compatibility_score": match.compatibility_score,
                "matched_at": match.matched_at,
                "has_conversation": match.has_conversation,
                "last_message": preview.get("body", ""),
                "last_message_at": preview.get("created_at"),
                "unread_count": preview.get("unread_count", 0),
                "conversation_id": preview.get("conversation_id"),
                "is_new": not match.has_conversation,
            })
        return rows
