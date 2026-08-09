"""Compatibility scoring engine.

Pure functions over plain dicts — no ORM, no Django, no other module. That makes
the engine unit-testable in isolation and trivially portable to a separate
matching service (or a model-serving endpoint) later.

A score is 0-100 and is the weighted sum of six dimensions:

    distance    how close they are, relative to the seeker's stated maximum
    age         how well the candidate sits inside the desired band
    interests   Jaccard overlap of interest sets
    lifestyle   agreement on smoking / drinking / children
    goals       agreement on what the relationship is for
    activity    recency of activity and profile completeness

Weights live in ``settings.ZYNORA["MATCH_SCORE_WEIGHTS"]`` so they can be tuned
without a deploy.
"""
import math

from django.conf import settings

from apps.common.utils import haversine_km


def _weights():
    return settings.ZYNORA["MATCH_SCORE_WEIGHTS"]


# ---------------------------------------------------------------------------
# Dimension scorers — each returns 0.0-1.0
# ---------------------------------------------------------------------------
def score_distance(seeker, candidate, max_distance_km):
    """1.0 at zero distance, decaying to 0.0 at the seeker's limit."""
    distance = haversine_km(
        seeker.get("latitude"), seeker.get("longitude"),
        candidate.get("latitude"), candidate.get("longitude"),
    )
    if distance is None:
        # Unknown location is neutral, not disqualifying.
        return 0.5, None
    if not max_distance_km:
        return 0.5, distance
    if distance >= max_distance_km:
        return 0.0, distance
    # Square-root decay: nearby candidates are not over-rewarded.
    return round(1.0 - math.sqrt(distance / max_distance_km), 4), distance


def score_age(candidate_age, min_age, max_age):
    if candidate_age is None:
        return 0.5
    if min_age <= candidate_age <= max_age:
        midpoint = (min_age + max_age) / 2
        span = max((max_age - min_age) / 2, 1)
        # Peak in the middle of the band, still strong at the edges.
        return round(1.0 - 0.25 * abs(candidate_age - midpoint) / span, 4)
    # Outside the band: fall off by one tenth per year of overshoot.
    overshoot = min_age - candidate_age if candidate_age < min_age else candidate_age - max_age
    return round(max(0.0, 0.5 - overshoot * 0.1), 4)


def score_interests(seeker_interests, candidate_interests):
    """Jaccard similarity, with a bonus for any overlap at all."""
    a = {i.lower() for i in seeker_interests or []}
    b = {i.lower() for i in candidate_interests or []}
    if not a or not b:
        return 0.3
    union = a | b
    shared = a & b
    jaccard = len(shared) / len(union)
    bonus = 0.15 if shared else 0.0
    return round(min(jaccard * 1.6 + bonus, 1.0), 4)


def score_lifestyle(seeker_prefs, candidate):
    """Compare stated preferences against the candidate's declared lifestyle."""
    checks = (
        (seeker_prefs.get("smoking_preference"), candidate.get("smoking")),
        (seeker_prefs.get("drinking_preference"), candidate.get("drinking")),
        (seeker_prefs.get("children_preference"), candidate.get("children")),
    )
    considered, points = 0, 0.0
    for wanted, actual in checks:
        if not wanted or wanted == "prefer_not":
            continue
        considered += 1
        if not actual:
            points += 0.5           # unknown is neutral
        elif wanted == actual:
            points += 1.0
        elif {wanted, actual} == {"never", "socially"}:
            points += 0.6           # adjacent answers are near-compatible
        elif {wanted, actual} == {"socially", "regularly"}:
            points += 0.5

    religion = (seeker_prefs.get("preferred_religion") or "").strip().lower()
    if religion:
        considered += 1
        points += 1.0 if religion == (candidate.get("religion") or "").lower() else 0.2

    languages = {l.lower() for l in seeker_prefs.get("preferred_languages") or []}
    if languages:
        considered += 1
        spoken = {l.lower() for l in candidate.get("languages") or []}
        points += 1.0 if languages & spoken else 0.2

    return round(points / considered, 4) if considered else 0.5


def score_goals(seeker_prefs, candidate):
    wanted = seeker_prefs.get("preferred_relationship_goals") or []
    actual = candidate.get("relationship_goal")
    if not wanted:
        return 0.6
    if not actual:
        return 0.4
    if actual in wanted:
        return 1.0
    # 'unsure' is not a mismatch, just unresolved.
    return 0.5 if actual == "unsure" else 0.15


def score_activity(candidate):
    """Rewards complete, photographed, recently-seen profiles."""
    completion = (candidate.get("completion_score") or 0) / 100
    photos = min((candidate.get("photo_count") or 0) / 3, 1.0)
    recency = candidate.get("activity_recency", 0.5)
    return round(completion * 0.4 + photos * 0.3 + recency * 0.3, 4)


def score_education(seeker_prefs, candidate):
    wanted = seeker_prefs.get("preferred_education_levels") or []
    if not wanted:
        return None
    return 1.0 if candidate.get("education_level") in wanted else 0.3


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------
def compatibility(seeker_profile, seeker_prefs, candidate_profile):
    """Return ``(score_0_100, breakdown_dict)``.

    All three arguments are plain dicts as produced by
    ``profiles.interface.get_match_payloads`` and ``get_preferences``.
    """
    prefs = seeker_prefs or {}
    weights = _weights()

    distance_score, distance_km = score_distance(
        seeker_profile, candidate_profile, prefs.get("max_distance_km", 100)
    )
    dimensions = {
        "distance": distance_score,
        "age": score_age(
            candidate_profile.get("age"),
            prefs.get("min_age", 18),
            prefs.get("max_age", 99),
        ),
        "interests": score_interests(
            seeker_profile.get("interests"), candidate_profile.get("interests")
        ),
        "lifestyle": score_lifestyle(prefs, candidate_profile),
        "goals": score_goals(prefs, candidate_profile),
        "activity": score_activity(candidate_profile),
    }

    total = sum(dimensions[name] * weights.get(name, 0) for name in dimensions)

    # Education is an optional modifier rather than a weighted dimension.
    education = score_education(prefs, candidate_profile)
    if education is not None:
        total = total * 0.92 + education * 0.08
        dimensions["education"] = education

    # A boosted profile gets a small, bounded lift — never enough to outrank
    # a genuinely better match.
    if candidate_profile.get("is_boosted"):
        total = min(total * 1.08, 1.0)

    score = int(round(max(0.0, min(total, 1.0)) * 100))
    breakdown = {
        "score": score,
        "distance_km": distance_km,
        "dimensions": {k: round(v, 3) for k, v in dimensions.items()},
        "shared_interests": sorted(
            {i.lower() for i in seeker_profile.get("interests") or []}
            & {i.lower() for i in candidate_profile.get("interests") or []}
        ),
    }
    return score, breakdown


def passes_hard_filters(seeker_prefs, candidate_profile, candidate_account, distance_km):
    """Non-negotiable exclusions, applied before scoring.

    Returns ``(bool, reason)`` — the reason is useful when debugging an empty feed.
    """
    prefs = seeker_prefs or {}

    if not candidate_profile.get("is_visible", True):
        return False, "profile hidden"

    interested_in = prefs.get("interested_in") or []
    if interested_in and candidate_profile.get("gender") not in interested_in:
        return False, "gender preference"

    age = candidate_profile.get("age")
    if age is not None:
        if age < prefs.get("min_age", 18) or age > prefs.get("max_age", 99):
            return False, "outside age range"

    if prefs.get("with_photos_only", True) and not candidate_profile.get("photo_count"):
        return False, "no photos"

    if prefs.get("verified_only") and not candidate_account.get("is_verified"):
        return False, "not verified"

    if not prefs.get("show_me_globally") and distance_km is not None:
        if distance_km > prefs.get("max_distance_km", 100):
            return False, "too far"

    return True, ""
