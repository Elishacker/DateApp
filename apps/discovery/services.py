"""Candidate feed assembly.

Discovery owns no tables. It is a pure composition service: build the eligible
pool from accounts, subtract what likes/matches/reports exclude, rank through
matching, then hydrate into render-ready cards. Every input arrives through a
contract, which is why this module can move to its own deployment unchanged.
"""
import logging

from apps.common.registry import services
from apps.common.services import CacheService

logger = logging.getLogger(__name__)

POOL_SIZE = 400
FEED_CACHE_SECONDS = 180

#: Below this many results the feed widens its radius rather than look empty.
MIN_FEED_SIZE = 10
#: Multiples of the member's stated distance to try, in order.
DISTANCE_EXPANSION_STEPS = (3, 10, 100)


class DiscoveryService:
    @staticmethod
    def build_feed(user_id, limit=20, refresh=False):
        """Return a list of render-ready candidate cards, best match first."""
        user_id = str(user_id)

        if not refresh:
            cached = CacheService.get("discovery", "feed", user_id)
            if cached:
                return cached[:limit]

        excluded = DiscoveryService._excluded_ids(user_id)
        pool = services.accounts.list_dateable_ids(exclude_ids=excluded, limit=POOL_SIZE)
        if not pool:
            return []

        cards = DiscoveryService._rank_and_hydrate(user_id, pool, max(limit * 3, 60))
        CacheService.set("discovery", "feed", user_id, value=cards, ttl=FEED_CACHE_SECONDS)
        return cards[:limit]

    @staticmethod
    def _rank_and_hydrate(user_id, pool, wanted):
        """Rank a pool, widening the radius if the result is too thin.

        A sparse local pool should widen the search, not show an empty feed.
        Members are far more forgiving about distance than about being told
        there is nobody. Distance is the only filter relaxed — gender, age and
        the photo/verified requirements are choices, not geography, and the
        member's stored preferences are never modified.
        """
        ranked = services.matching.rank_candidates(user_id, pool, limit=wanted)

        expanded_from = None
        if len(ranked) < MIN_FEED_SIZE:
            prefs = services.profiles.get_preferences(user_id) or {}
            original = prefs.get("max_distance_km") or 100
            for multiplier in DISTANCE_EXPANSION_STEPS:
                widened = services.matching.rank_candidates(
                    user_id, pool, limit=wanted,
                    preference_overrides={"max_distance_km": original * multiplier},
                )
                if len(widened) > len(ranked):
                    ranked, expanded_from = widened, original
                if len(ranked) >= MIN_FEED_SIZE:
                    break

        cards = DiscoveryService._hydrate(user_id, ranked)
        if expanded_from:
            for card in cards:
                card["outside_range"] = (
                    card["distance_km"] is not None
                    and card["distance_km"] > expanded_from
                )
        return cards

    @staticmethod
    def invalidate(user_id):
        CacheService.delete("discovery", "feed", str(user_id))

    # ---- named feeds --------------------------------------------------------
    @staticmethod
    def nearby(user_id, limit=20, radius_km=None):
        """Closest first, within the member's own stated distance."""
        if radius_km is None:
            prefs = services.profiles.get_preferences(str(user_id)) or {}
            radius_km = prefs.get("max_distance_km") or 100

        cards = DiscoveryService.build_feed(user_id, limit=60)
        near = [c for c in cards
                if c["distance_km"] is not None and c["distance_km"] <= radius_km]
        near.sort(key=lambda c: c["distance_km"])

        # Nobody inside the radius: fall back to nearest-first overall rather
        # than an empty tab.
        if not near:
            located = [c for c in cards if c["distance_km"] is not None]
            located.sort(key=lambda c: c["distance_km"])
            return located[:limit]
        return near[:limit]

    @staticmethod
    def online_now(user_id, limit=20):
        excluded = DiscoveryService._excluded_ids(user_id)
        pool = services.accounts.list_online_ids(exclude_ids=excluded, limit=200)
        if not pool:
            return []
        return DiscoveryService._rank_and_hydrate(str(user_id), pool, limit * 3)[:limit]

    @staticmethod
    def newest(user_id, limit=20, days=30):
        """Members who joined most recently, still filtered by preferences."""
        excluded = DiscoveryService._excluded_ids(user_id)
        pool = services.accounts.list_recently_joined_ids(
            exclude_ids=excluded, limit=200, days=days
        )
        if not pool:
            return []
        return DiscoveryService._rank_and_hydrate(str(user_id), pool, limit * 3)[:limit]

    @staticmethod
    def verified_only(user_id, limit=20):
        excluded = DiscoveryService._excluded_ids(user_id)
        pool = services.accounts.list_dateable_ids(exclude_ids=excluded, limit=POOL_SIZE)
        cards = DiscoveryService._rank_and_hydrate(str(user_id), pool, POOL_SIZE)
        return [c for c in cards if c["user"]["is_verified"]][:limit]

    @staticmethod
    def admirers(user_id, limit=30):
        """People who liked you. Gated by subscriptions at the view layer."""
        ids = services.likes.get_admirer_ids(str(user_id))[:limit]
        if not ids:
            return []
        ranked = services.matching.rank_candidates(
            user_id, ids, limit=limit, apply_hard_filters=False
        )
        cards = DiscoveryService._hydrate(str(user_id), ranked)
        kinds = services.likes.get_admirer_kinds(str(user_id), ids)
        for card in cards:
            admirer_id = card["user"]["id"]
            kind = kinds.get(admirer_id, "like")
            card["admirer_kind"] = kind
            card["admirer_is_super"] = kind == "super_like"
            card["admirer_label"] = "Super liked you" if kind == "super_like" else "Liked you"
            card["super_like_message"] = services.likes.get_super_like_message(
                admirer_id, str(user_id)
            )
        return cards

    # ---- search -------------------------------------------------------------
    #: Which field group each search scope asks the profiles service for.
    SEARCH_SCOPES = {
        "all": None,
        "region": ["region"],
        "country": ["country"],
        "job": ["job"],
        "interests": ["interests"],
    }

    @staticmethod
    def search(user_id, query, scope="all", limit=40, respect_preferences=False):
        """Find members by name, region, country, job title or interests.

        Search is deliberately *not* filtered by the member's match preferences
        by default: looking someone up is a different intent from browsing a
        feed, and silently hiding results people asked for is worse than showing
        someone outside their usual range.
        """
        user_id = str(user_id)
        query = (query or "").strip()
        if len(query) < 2:
            return {"query": query, "results": [], "count": 0,
                    "message": "Type at least two characters."}

        # Blocks always apply; self never appears.
        excluded = {user_id, *services.reports.get_blocked_user_ids(user_id)}

        fields = DiscoveryService.SEARCH_SCOPES.get(scope, None)
        matched_ids = []

        # Name is owned by accounts, everything else by profiles.
        if scope in ("all", "name"):
            matched_ids += services.accounts.search_ids(
                query, exclude_ids=list(excluded), limit=200
            )
        if scope != "name":
            matched_ids += services.profiles.search_ids(
                query, exclude_ids=list(excluded), limit=200, fields=fields
            )

        # Preserve first-seen order while removing duplicates.
        seen = set()
        ordered = [i for i in matched_ids if not (i in seen or seen.add(i))]
        if not ordered:
            return {"query": query, "results": [], "count": 0,
                    "message": f"Nobody found for “{query}”."}

        ranked = services.matching.rank_candidates(
            user_id, ordered, limit=limit,
            apply_hard_filters=respect_preferences,
        )
        cards = DiscoveryService._hydrate(user_id, ranked)
        return {
            "query": query,
            "results": cards,
            "count": len(cards),
            "message": "" if cards else f"Nobody found for “{query}”.",
        }

    # ---- internals ----------------------------------------------------------
    @staticmethod
    def _excluded_ids(user_id):
        """Everyone who must never appear: self, passed on, matched, blocked.

        Liked profiles are deliberately *not* excluded. Removing someone the
        moment you like them hides the people you were most interested in and
        empties the feed fast; they stay visible with a liked state instead.
        Matches move to the Matches tab, so they do leave.
        """
        excluded = {str(user_id)}
        excluded.update(services.likes.get_passed_ids(user_id))
        excluded.update(services.matches.get_matched_user_ids(user_id))
        excluded.update(services.reports.get_blocked_user_ids(user_id))
        return list(excluded)

    @staticmethod
    def _hydrate(user_id, ranked_rows):
        """Turn scored rows into cards the template can render without logic."""
        if not ranked_rows:
            return []

        candidate_ids = [row["user_id"] for row in ranked_rows]
        refs = services.accounts.get_user_refs(candidate_ids)
        liked = services.likes.get_liked_map(user_id, candidate_ids)
        # How popular each candidate is. One grouped query for the whole page.
        received = services.likes.count_received_bulk(candidate_ids)

        cards = []
        for row in ranked_rows:
            ref = refs.get(row["user_id"])
            card_data = services.profiles.get_public_card(row["user_id"], viewer_id=user_id)
            if not ref or not card_data:
                continue

            cards.append({
                "user": ref,
                "headline": card_data["headline"],
                "bio": card_data["bio"],
                "job_title": card_data["job_title"],
                "school": card_data["school"],
                "location_label": card_data["location_label"],
                "region_label": card_data["region_label"],
                "photos": card_data["photos"],
                "primary_photo_url": card_data["primary_photo_url"],
                "score": row["score"],
                "score_label": DiscoveryService._score_label(row["score"]),
                "distance_km": row["distance_km"],
                "distance_label": DiscoveryService._distance_label(row["distance_km"]),
                "is_boosted": row["is_boosted"],
                "outside_range": False,
                "liked_kind": liked.get(row["user_id"], ""),
                "has_liked": row["user_id"] in liked,
                "is_super_liked": liked.get(row["user_id"]) == "super_like",
                **DiscoveryService._like_counts(received.get(row["user_id"])),
            })
        return cards

    @staticmethod
    def _like_counts(counts):
        """Card fields for how many likes this person has received."""
        counts = counts or {"likes": 0, "super_likes": 0, "total": 0}
        return {
            "like_count": counts["likes"],
            "super_like_count": counts["super_likes"],
            "received_total": counts["total"],
            # Pre-phrased so the template only prints. Super likes are called
            # out separately because they are the scarcer, stronger signal.
            "received_label": DiscoveryService._received_label(counts),
        }

    @staticmethod
    def _received_label(counts):
        if not counts["total"]:
            return ""
        parts = [f"{counts['likes']} like{'s' if counts['likes'] != 1 else ''}"] \
            if counts["likes"] else []
        if counts["super_likes"]:
            parts.append(
                f"{counts['super_likes']} super like"
                f"{'s' if counts['super_likes'] != 1 else ''}"
            )
        return " · ".join(parts)

    @staticmethod
    def explain_empty(user_id):
        """Say *why* a feed came back empty, using the engine's own tallies.

        Returns ``{"headline", "reasons": [{"text", "action_url", "action_label"}]}``
        — already phrased for display, because the template does no logic.
        """
        user_id = str(user_id)
        diagnostics = services.matching.last_run_diagnostics(user_id)
        prefs = services.profiles.get_preferences(user_id) or {}
        profile = services.profiles.get_profile(user_id) or {}

        reasons = []

        # The member's own profile can be the reason nobody sees them back.
        if not profile.get("photo_count"):
            reasons.append({
                "text": "You haven't added a photo yet, so you won't appear for others either.",
                "action_url": "/profile/photos/",
                "action_label": "Add a photo",
            })
        if not profile.get("latitude"):
            reasons.append({
                "text": "Your location isn't set, so distance can't be used to rank matches.",
                "action_url": "/profile/edit/",
                "action_label": "Set your location",
            })

        rejected = (diagnostics or {}).get("filtered_out", {})
        considered = (diagnostics or {}).get("considered", 0)

        # Phrase each filter tally as something the member can act on.
        copy = {
            "too far": (
                "{count} people were outside your {distance} km limit.",
                "/profile/preferences/", "Widen your distance",
            ),
            "outside age range": (
                "{count} people were outside your {min_age}–{max_age} age range.",
                "/profile/preferences/", "Widen your age range",
            ),
            "gender preference": (
                "{count} people didn't match who you're looking for.",
                "/profile/preferences/", "Review preferences",
            ),
            "no photos": (
                "{count} people have no photos, and you've asked to only see profiles with photos.",
                "/profile/preferences/", "Allow profiles without photos",
            ),
            "not verified": (
                "{count} people aren't verified, and you've asked to only see verified profiles.",
                "/profile/preferences/", "Allow unverified profiles",
            ),
            "profile hidden": (
                "{count} profiles are currently hidden by their owners.", "", "",
            ),
        }

        for key, count in sorted(rejected.items(), key=lambda kv: -kv[1]):
            entry = copy.get(key)
            if not entry or not count:
                continue
            text, url, label = entry
            reasons.append({
                "text": text.format(
                    count=count,
                    distance=prefs.get("max_distance_km", 100),
                    min_age=prefs.get("min_age", 18),
                    max_age=prefs.get("max_age", 99),
                ),
                "action_url": url,
                "action_label": label,
            })

        if considered == 0 and not reasons:
            reasons.append({
                "text": "There are no new members to show — you've seen everyone who matches.",
                "action_url": "/profile/preferences/",
                "action_label": "Widen your preferences",
            })

        return {
            "headline": (
                f"We looked at {considered} profiles but none passed your filters."
                if considered else "Nobody new to show right now."
            ),
            "reasons": reasons,
        }

    @staticmethod
    def _score_label(score):
        """Presentation string computed here, not in the template."""
        if score >= 85:
            return "Exceptional match"
        if score >= 70:
            return "Great match"
        if score >= 55:
            return "Good match"
        if score >= 40:
            return "Worth a look"
        return "Something different"

    @staticmethod
    def _distance_label(distance_km):
        if distance_km is None:
            return "Distance unknown"
        if distance_km < 1:
            return "Less than 1 km away"
        if distance_km < 10:
            return f"{distance_km:.1f} km away"
        return f"{int(distance_km)} km away"
