"""Unit tests for the compatibility engine.

The engine is pure functions over dicts, so these tests need no database — which
is exactly the property that makes it portable to a standalone service.
"""
from django.test import SimpleTestCase

from apps.matching import engine


class DimensionScoreTests(SimpleTestCase):
    def test_distance_decays_with_range(self):
        near = {"latitude": -6.79, "longitude": 39.20}
        seeker = {"latitude": -6.79, "longitude": 39.20}
        score, distance = engine.score_distance(seeker, near, 100)
        self.assertAlmostEqual(distance, 0.0, places=1)
        self.assertEqual(score, 1.0)

    def test_distance_beyond_limit_scores_zero(self):
        seeker = {"latitude": -6.79, "longitude": 39.20}     # Dar es Salaam
        far = {"latitude": -1.29, "longitude": 36.82}        # Nairobi
        score, distance = engine.score_distance(seeker, far, 100)
        self.assertGreater(distance, 100)
        self.assertEqual(score, 0.0)

    def test_missing_location_is_neutral_not_disqualifying(self):
        score, distance = engine.score_distance({}, {}, 100)
        self.assertEqual(score, 0.5)
        self.assertIsNone(distance)

    def test_age_peaks_mid_band_and_falls_outside(self):
        inside = engine.score_age(30, 25, 35)
        edge = engine.score_age(35, 25, 35)
        outside = engine.score_age(40, 25, 35)
        self.assertGreater(inside, edge)
        self.assertGreater(edge, outside)
        self.assertGreaterEqual(outside, 0.0)

    def test_interests_reward_overlap(self):
        none = engine.score_interests(["music"], ["fishing"])
        some = engine.score_interests(["music", "travel"], ["music", "hiking"])
        identical = engine.score_interests(["music", "travel"], ["music", "travel"])
        self.assertLess(none, some)
        self.assertLess(some, identical)
        self.assertLessEqual(identical, 1.0)

    def test_goals_penalise_mismatch_but_forgive_unsure(self):
        aligned = engine.score_goals({"preferred_relationship_goals": ["long_term"]},
                                     {"relationship_goal": "long_term"})
        unsure = engine.score_goals({"preferred_relationship_goals": ["long_term"]},
                                    {"relationship_goal": "unsure"})
        opposed = engine.score_goals({"preferred_relationship_goals": ["long_term"]},
                                     {"relationship_goal": "short_term"})
        self.assertEqual(aligned, 1.0)
        self.assertGreater(unsure, opposed)


class CompatibilityTests(SimpleTestCase):
    def setUp(self):
        self.seeker = {
            "latitude": -6.79, "longitude": 39.20, "age": 30,
            "interests": ["music", "travel", "coffee"],
        }
        self.prefs = {
            "min_age": 25, "max_age": 35, "max_distance_km": 100,
            "preferred_relationship_goals": ["long_term"],
            "interested_in": ["woman"], "with_photos_only": True,
        }

    def _candidate(self, **overrides):
        base = {
            "latitude": -6.80, "longitude": 39.22, "age": 29, "gender": "woman",
            "interests": ["music", "travel", "hiking"],
            "relationship_goal": "long_term", "completion_score": 90,
            "photo_count": 4, "is_visible": True, "activity_recency": 1.0,
        }
        base.update(overrides)
        return base

    def test_score_is_bounded_and_explains_itself(self):
        score, breakdown = engine.compatibility(self.seeker, self.prefs, self._candidate())
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)
        self.assertEqual(breakdown["score"], score)
        self.assertIn("music", breakdown["shared_interests"])
        self.assertIn("distance", breakdown["dimensions"])

    def test_better_candidate_scores_higher(self):
        good, _ = engine.compatibility(self.seeker, self.prefs, self._candidate())
        poor, _ = engine.compatibility(self.seeker, self.prefs, self._candidate(
            latitude=-1.29, longitude=36.82, age=52,
            interests=["fishing"], relationship_goal="short_term",
            completion_score=10, photo_count=0,
        ))
        self.assertGreater(good, poor)

    def test_boost_lifts_but_cannot_exceed_the_maximum(self):
        plain, _ = engine.compatibility(self.seeker, self.prefs, self._candidate())
        boosted, _ = engine.compatibility(
            self.seeker, self.prefs, self._candidate(is_boosted=True)
        )
        self.assertGreaterEqual(boosted, plain)
        self.assertLessEqual(boosted, 100)


class HardFilterTests(SimpleTestCase):
    def setUp(self):
        self.prefs = {
            "interested_in": ["woman"], "min_age": 25, "max_age": 35,
            "max_distance_km": 100, "with_photos_only": True, "verified_only": False,
        }
        self.candidate = {
            "gender": "woman", "age": 30, "photo_count": 3, "is_visible": True,
        }
        self.account = {"is_verified": False}

    def test_matching_candidate_passes(self):
        allowed, reason = engine.passes_hard_filters(
            self.prefs, self.candidate, self.account, 20
        )
        self.assertTrue(allowed, reason)

    def test_wrong_gender_is_excluded(self):
        allowed, reason = engine.passes_hard_filters(
            self.prefs, {**self.candidate, "gender": "man"}, self.account, 20
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "gender preference")

    def test_hidden_profile_is_excluded(self):
        allowed, reason = engine.passes_hard_filters(
            self.prefs, {**self.candidate, "is_visible": False}, self.account, 20
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "profile hidden")

    def test_too_far_is_excluded_unless_global(self):
        allowed, _ = engine.passes_hard_filters(self.prefs, self.candidate, self.account, 500)
        self.assertFalse(allowed)

        globalised = {**self.prefs, "show_me_globally": True}
        allowed, _ = engine.passes_hard_filters(globalised, self.candidate, self.account, 500)
        self.assertTrue(allowed)

    def test_verified_only_excludes_unverified(self):
        allowed, reason = engine.passes_hard_filters(
            {**self.prefs, "verified_only": True}, self.candidate, self.account, 20
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "not verified")
