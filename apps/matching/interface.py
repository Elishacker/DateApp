"""Public contract of the matching service.

This is the module most likely to be extracted first (it is CPU-bound and
stateless), so every method here is already free of ORM objects.
"""
from apps.common.interface import ModuleInterface

from .models import CompatibilityScore
from .services import MatchingService


class MatchingInterface(ModuleInterface):
    name = "matching"
    depends_on = ("profiles", "accounts")

    def score_pair(self, seeker_id, candidate_id):
        return MatchingService.score_pair(seeker_id, candidate_id)

    def explain_pair(self, seeker_id, candidate_id):
        return MatchingService.explain_pair(seeker_id, candidate_id)

    def rank_candidates(self, seeker_id, candidate_ids, limit=50,
                        apply_hard_filters=True, preference_overrides=None):
        return MatchingService.rank_candidates(
            seeker_id, candidate_ids, limit=limit,
            apply_hard_filters=apply_hard_filters,
            preference_overrides=preference_overrides,
        )

    def top_scores_for(self, seeker_id, limit=20, min_score=0):
        """Read straight from the cache table — used by recommendation."""
        rows = CompatibilityScore.objects.filter(
            seeker_id=seeker_id, score__gte=min_score
        ).order_by("-score")[:limit]
        return [
            {
                "user_id": str(r.candidate_id),
                "score": r.score,
                "distance_km": r.distance_km,
                "breakdown": r.breakdown,
                "is_fresh": r.is_fresh,
            }
            for r in rows
        ]

    def invalidate(self, user_id):
        MatchingService.invalidate_for(user_id)
        return True

    def last_run_diagnostics(self, seeker_id):
        """Why the last ranking pass rejected what it rejected.

        Turns an empty feed from a mystery into an explanation — both for the
        member (``discovery`` uses it for the empty state) and for support.
        """
        from .models import MatchingRun

        run = MatchingRun.objects.filter(seeker_id=seeker_id).order_by("-created_at").first()
        if not run:
            return None
        return {
            "considered": run.candidates_considered,
            "scored": run.candidates_scored,
            "filtered_out": run.filtered_out,
            "top_score": run.top_score,
            "duration_ms": run.duration_ms,
            "ran_at": run.created_at.isoformat(),
        }

    def cached_score(self, seeker_id, candidate_id):
        row = CompatibilityScore.objects.filter(
            seeker_id=seeker_id, candidate_id=candidate_id
        ).first()
        return row.score if row and row.is_fresh else None


service = MatchingInterface()
