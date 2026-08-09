"""Recommendation set generation."""
import logging

from django.utils import timezone

from apps.common.registry import services

from .models import Recommendation, RecommendationSet

logger = logging.getLogger(__name__)

SET_TTL_HOURS = 24
DEFAULT_SIZE = 10


class RecommendationService:
    @staticmethod
    def build_all(user_id):
        """Rebuild every set for one member. Safe to run repeatedly."""
        user_id = str(user_id)
        excluded = RecommendationService._excluded(user_id)
        pool = services.accounts.list_dateable_ids(exclude_ids=excluded, limit=300)
        if not pool:
            return 0

        ranked = services.matching.rank_candidates(user_id, pool, limit=100)
        if not ranked:
            return 0

        refs = services.accounts.get_user_refs([r["user_id"] for r in ranked])
        expires = timezone.now() + timezone.timedelta(hours=SET_TTL_HOURS)

        Recommendation.objects.filter(user_id=user_id).delete()

        builders = (
            (RecommendationSet.TOP_PICKS, RecommendationService._top_picks),
            (RecommendationSet.MOST_COMPATIBLE, RecommendationService._most_compatible),
            (RecommendationSet.NEARBY, RecommendationService._nearby),
            (RecommendationSet.RECENTLY_ACTIVE, RecommendationService._recently_active),
        )

        created = 0
        for set_name, builder in builders:
            for rank, row in enumerate(builder(ranked, refs), start=1):
                Recommendation.objects.update_or_create(
                    user_id=user_id, candidate_id=row["user_id"], set_name=set_name,
                    defaults={
                        "rank": rank, "score": row["score"],
                        "reason": RecommendationService._reason(set_name, row),
                        "distance_km": row["distance_km"], "expires_at": expires,
                    },
                )
                created += 1

        logger.info("built %d recommendation(s) for %s", created, user_id)
        return created

    # ---- set builders -------------------------------------------------------
    @staticmethod
    def _top_picks(ranked, refs):
        """Best overall, but only from complete, verified-ish profiles."""
        picks = [
            row for row in ranked
            if row["score"] >= 60 and (refs.get(row["user_id"]) or {}).get("avatar_url")
        ]
        return picks[:DEFAULT_SIZE]

    @staticmethod
    def _most_compatible(ranked, refs):
        return sorted(ranked, key=lambda r: r["score"], reverse=True)[:DEFAULT_SIZE]

    @staticmethod
    def _nearby(ranked, refs):
        near = [r for r in ranked if r["distance_km"] is not None]
        return sorted(near, key=lambda r: r["distance_km"])[:DEFAULT_SIZE]

    @staticmethod
    def _recently_active(ranked, refs):
        online = [r for r in ranked if (refs.get(r["user_id"]) or {}).get("is_online")]
        return (online or ranked)[:DEFAULT_SIZE]

    @staticmethod
    def _reason(set_name, row):
        shared = len(row.get("shared_interests", []))
        if set_name == RecommendationSet.NEARBY and row["distance_km"] is not None:
            return f"{int(row['distance_km'])} km away"
        if set_name == RecommendationSet.MOST_COMPATIBLE:
            return f"{row['score']}% compatible"
        if shared:
            return f"{shared} shared interest{'s' if shared > 1 else ''}"
        return f"{row['score']}% match"

    # ---- reads --------------------------------------------------------------
    @staticmethod
    def get_set(user_id, set_name, limit=DEFAULT_SIZE, mark_shown=True):
        """Render-ready cards for one set; rebuilds lazily when stale."""
        rows = list(
            Recommendation.objects.filter(
                user_id=user_id, set_name=set_name, expires_at__gt=timezone.now()
            ).order_by("rank")[:limit]
        )
        if not rows:
            RecommendationService.build_all(user_id)
            rows = list(
                Recommendation.objects.filter(
                    user_id=user_id, set_name=set_name
                ).order_by("rank")[:limit]
            )

        candidate_ids = [str(r.candidate_id) for r in rows]
        refs = services.accounts.get_user_refs(candidate_ids)
        liked = services.likes.get_liked_map(user_id, candidate_ids)

        cards = []
        for row in rows:
            ref = refs.get(str(row.candidate_id))
            if not ref:
                continue
            card = services.profiles.get_public_card(str(row.candidate_id), viewer_id=user_id)
            if not card:
                continue
            # Same shape as a discovery card so both render through
            # components/profile_card.html — one card, one place to change it.
            cards.append({
                "user": ref,
                "headline": card["headline"],
                "job_title": card["job_title"],
                "location_label": card["location_label"],
                "region_label": card["region_label"],
                "primary_photo_url": card["primary_photo_url"],
                "score": row.score,
                "reason": row.reason,
                "distance_km": row.distance_km,
                "rank": row.rank,
                "liked_kind": liked.get(str(row.candidate_id), ""),
                "has_liked": str(row.candidate_id) in liked,
                "is_super_liked": liked.get(str(row.candidate_id)) == "super_like",
            })
            if mark_shown:
                row.mark_shown()
        return cards

    @staticmethod
    def all_sets(user_id):
        """Every set, prepared for the recommendations page."""
        return [
            {
                "key": value,
                "title": label,
                "cards": RecommendationService.get_set(user_id, value, mark_shown=False),
            }
            for value, label in RecommendationSet.choices
        ]

    @staticmethod
    def mark_acted(user_id, candidate_id):
        return Recommendation.objects.filter(
            user_id=user_id, candidate_id=candidate_id
        ).update(was_acted_on=True)

    @staticmethod
    def invalidate(user_id):
        return Recommendation.objects.filter(user_id=user_id).delete()[0]

    @staticmethod
    def _excluded(user_id):
        excluded = {user_id}
        excluded.update(services.likes.get_passed_ids(user_id))
        excluded.update(services.matches.get_matched_user_ids(user_id))
        excluded.update(services.reports.get_blocked_user_ids(user_id))
        return list(excluded)

    @staticmethod
    def effectiveness():
        """How often a shown recommendation led to a swipe — tunes the engine."""
        shown = Recommendation.objects.filter(was_shown=True).count()
        acted = Recommendation.objects.filter(was_acted_on=True).count()
        return {
            "shown": shown,
            "acted_on": acted,
            "action_rate": round(acted / shown * 100, 2) if shown else 0.0,
        }
