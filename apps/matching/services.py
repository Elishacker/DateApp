"""Matching orchestration: gather inputs, run the engine, cache the results."""
import logging
import time

from django.utils import timezone

from apps.common.registry import services
from apps.common.services import CacheService

from . import engine
from .models import CompatibilityScore, MatchingRun

logger = logging.getLogger(__name__)

SCORE_TTL_HOURS = 12
CACHE_TTL_SECONDS = 600


class MatchingService:
    """Stateless coordinator. All data arrives through other services' contracts."""

    @staticmethod
    def score_pair(seeker_id, candidate_id, use_cache=True):
        """Compatibility for one pair, 0-100."""
        seeker_id, candidate_id = str(seeker_id), str(candidate_id)
        if seeker_id == candidate_id:
            return None

        if use_cache:
            cached = CacheService.get("matching", seeker_id, candidate_id)
            if cached is not None:
                return cached

            row = CompatibilityScore.objects.filter(
                seeker_id=seeker_id, candidate_id=candidate_id
            ).first()
            if row and row.is_fresh:
                CacheService.set("matching", seeker_id, candidate_id,
                                 value=row.score, ttl=CACHE_TTL_SECONDS)
                return row.score

        payloads = services.profiles.get_match_payloads([seeker_id, candidate_id])
        seeker = payloads.get(seeker_id)
        candidate = payloads.get(candidate_id)
        if not seeker or not candidate:
            return None

        prefs = services.profiles.get_preferences(seeker_id) or {}
        candidate["activity_recency"] = MatchingService._activity_recency(candidate_id)

        score, breakdown = engine.compatibility(seeker, prefs, candidate)
        MatchingService._store(seeker_id, candidate_id, score, breakdown)
        return score

    @staticmethod
    def explain_pair(seeker_id, candidate_id):
        """Full breakdown — powers the 'why you match' panel."""
        seeker_id, candidate_id = str(seeker_id), str(candidate_id)
        payloads = services.profiles.get_match_payloads([seeker_id, candidate_id])
        seeker, candidate = payloads.get(seeker_id), payloads.get(candidate_id)
        if not seeker or not candidate:
            return None
        prefs = services.profiles.get_preferences(seeker_id) or {}
        candidate["activity_recency"] = MatchingService._activity_recency(candidate_id)
        _, breakdown = engine.compatibility(seeker, prefs, candidate)
        return breakdown

    @staticmethod
    def rank_candidates(seeker_id, candidate_ids, limit=50, apply_hard_filters=True,
                        preference_overrides=None):
        """Score a pool in one pass. Returns rows sorted best-first.

        This is the hot path behind discovery: three bulk contract calls, then
        pure in-memory scoring.

        ``preference_overrides`` relaxes named filters for this call only —
        discovery uses it to widen the search radius when a member's local pool
        is too thin to fill a feed. Stored preferences are never modified.
        """
        started = time.monotonic()
        seeker_id = str(seeker_id)
        candidate_ids = [str(c) for c in candidate_ids if str(c) != seeker_id]
        if not candidate_ids:
            return []

        payloads = services.profiles.get_match_payloads([seeker_id, *candidate_ids])
        seeker = payloads.get(seeker_id)
        if not seeker:
            return []

        prefs = dict(services.profiles.get_preferences(seeker_id) or {})
        if preference_overrides:
            prefs.update(preference_overrides)
        accounts = services.accounts.get_user_refs(candidate_ids)

        rows, rejected = [], {}
        for candidate_id in candidate_ids:
            candidate = payloads.get(candidate_id)
            account = accounts.get(candidate_id)
            if not candidate or not account:
                rejected["missing_data"] = rejected.get("missing_data", 0) + 1
                continue

            candidate["activity_recency"] = MatchingService._recency_from_ref(account)
            score, breakdown = engine.compatibility(seeker, prefs, candidate)

            if apply_hard_filters:
                allowed, reason = engine.passes_hard_filters(
                    prefs, candidate, account, breakdown["distance_km"]
                )
                if not allowed:
                    rejected[reason] = rejected.get(reason, 0) + 1
                    continue

            rows.append({
                "user_id": candidate_id,
                "score": score,
                "distance_km": breakdown["distance_km"],
                "shared_interests": breakdown["shared_interests"],
                "breakdown": breakdown["dimensions"],
                "is_boosted": candidate.get("is_boosted", False),
            })

        # Boosted profiles surface earlier without displacing a much better match.
        rows.sort(key=lambda r: (r["is_boosted"], r["score"]), reverse=True)
        rows = rows[:limit]

        MatchingService._persist_batch(seeker_id, rows)
        MatchingRun.objects.create(
            seeker_id=seeker_id,
            candidates_considered=len(candidate_ids),
            candidates_scored=len(rows),
            filtered_out=rejected,
            duration_ms=int((time.monotonic() - started) * 1000),
            top_score=rows[0]["score"] if rows else 0,
        )
        return rows

    # ---- cache management ---------------------------------------------------
    @staticmethod
    def invalidate_for(user_id):
        """Called when a profile or preference set changes."""
        CompatibilityScore.objects.filter(seeker_id=user_id).delete()
        CompatibilityScore.objects.filter(candidate_id=user_id).delete()
        logger.debug("invalidated matching cache for %s", user_id)

    @staticmethod
    def _store(seeker_id, candidate_id, score, breakdown):
        CompatibilityScore.objects.update_or_create(
            seeker_id=seeker_id, candidate_id=candidate_id,
            defaults={
                "score": score,
                "distance_km": breakdown.get("distance_km"),
                "breakdown": breakdown.get("dimensions", {}),
                "expires_at": timezone.now() + timezone.timedelta(hours=SCORE_TTL_HOURS),
            },
        )
        CacheService.set("matching", seeker_id, candidate_id, value=score, ttl=CACHE_TTL_SECONDS)

    @staticmethod
    def _persist_batch(seeker_id, rows):
        expires = timezone.now() + timezone.timedelta(hours=SCORE_TTL_HOURS)
        for row in rows:
            CompatibilityScore.objects.update_or_create(
                seeker_id=seeker_id, candidate_id=row["user_id"],
                defaults={
                    "score": row["score"], "distance_km": row["distance_km"],
                    "breakdown": row["breakdown"], "expires_at": expires,
                },
            )

    @staticmethod
    def _activity_recency(user_id):
        ref = services.accounts.get_user_ref(user_id)
        return MatchingService._recency_from_ref(ref)

    @staticmethod
    def _recency_from_ref(ref):
        if not ref:
            return 0.3
        return 1.0 if ref.get("is_online") else 0.6
