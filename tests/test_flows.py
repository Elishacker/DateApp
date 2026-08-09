"""End-to-end tests over the service contracts.

Every assertion goes through a module's public interface rather than its models,
so these tests keep passing if a module is extracted.
"""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.common.registry import services

User = get_user_model()


def make_member(email, username, *, gender="woman", age=28, city="Dar es Salaam"):
    """Create a fully onboarded member through the contracts."""
    record = services.accounts.create_account(
        email=email, username=username, password="ZynoraTest2026!",
        first_name=username.title(),
        date_of_birth=date.today() - timedelta(days=age * 365),
        accepted_terms=True,
    )
    user = User.objects.get(id=record["id"])
    user.is_email_verified = True
    user.status = "active"
    user.has_completed_onboarding = True
    user.save()

    services.profiles.update_profile(
        str(user.id), gender=gender, headline="Test headline",
        bio="A bio long enough to count toward profile completion scoring.",
        relationship_goal="long_term",
        interests=["Music", "Travel", "Coffee"],
    )
    services.profiles.set_location(
        str(user.id), latitude=-6.79, longitude=39.20, city=city, country="Tanzania"
    )
    return user


class RegistrationFlowTests(TestCase):
    def test_registering_bootstraps_every_dependent_module(self):
        """One event should fan out to profiles, onboarding, subscriptions, audit."""
        user = make_member("newbie@test.zynora.app", "newbie")
        user_id = str(user.id)

        self.assertTrue(services.profiles.exists(user_id))
        self.assertIsNotNone(services.profiles.get_preferences(user_id))
        self.assertIsNotNone(services.onboarding.get_state(user_id))

        # Free plan resolves without any subscription row existing.
        plan = services.subscriptions.get_current_plan(user_id)
        self.assertTrue(plan["is_free"])

        # Audit recorded the registration.
        activity = services.audit.activity_about(user_id)
        self.assertTrue(any(e["action"] == "user.registered" for e in activity))

    def test_duplicate_email_is_rejected(self):
        make_member("dupe@test.zynora.app", "dupeone")
        from apps.common.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            services.accounts.create_account(
                email="dupe@test.zynora.app", username="dupetwo",
                password="ZynoraTest2026!", accepted_terms=True,
            )


class MatchFlowTests(TestCase):
    def setUp(self):
        self.alice = make_member("alice@test.zynora.app", "alice", gender="woman")
        self.bob = make_member("bob@test.zynora.app", "bob", gender="man")
        services.profiles.update_preferences(
            str(self.alice.id), interested_in=["man"], with_photos_only=False
        )
        services.profiles.update_preferences(
            str(self.bob.id), interested_in=["woman"], with_photos_only=False
        )

    def test_mutual_like_creates_a_match_and_a_conversation(self):
        first = services.likes.swipe(str(self.alice.id), str(self.bob.id), "like")
        self.assertFalse(first["matched"])

        second = services.likes.swipe(str(self.bob.id), str(self.alice.id), "like")
        self.assertTrue(second["matched"])

        self.assertTrue(services.matches.are_matched(str(self.alice.id), str(self.bob.id)))

        # The chat service opened a conversation off the MATCH_CREATED event.
        conversation_id = services.chat.get_conversation_id_for_match(second["match_id"])
        self.assertIsNotNone(conversation_id)

        # Both sides were notified.
        self.assertGreater(services.notifications.get_unread_count(str(self.alice.id)), 0)
        self.assertGreater(services.notifications.get_unread_count(str(self.bob.id)), 0)

    def test_one_sided_like_creates_no_match(self):
        services.likes.swipe(str(self.alice.id), str(self.bob.id), "like")
        self.assertFalse(services.matches.are_matched(str(self.alice.id), str(self.bob.id)))
        self.assertIn(str(self.alice.id), services.likes.get_admirer_ids(str(self.bob.id)))

    def test_swiping_twice_is_rejected(self):
        from apps.common.exceptions import ValidationError

        services.likes.swipe(str(self.alice.id), str(self.bob.id), "like")
        with self.assertRaises(ValidationError):
            services.likes.swipe(str(self.alice.id), str(self.bob.id), "like")

    def test_blocking_ends_the_match_and_hides_both_ways(self):
        services.likes.swipe(str(self.alice.id), str(self.bob.id), "like")
        services.likes.swipe(str(self.bob.id), str(self.alice.id), "like")
        self.assertTrue(services.matches.are_matched(str(self.alice.id), str(self.bob.id)))

        services.reports.block_user(str(self.alice.id), str(self.bob.id), "test")

        self.assertTrue(
            services.reports.is_blocked_between(str(self.alice.id), str(self.bob.id))
        )
        # Symmetric: the blocked party also can't see the blocker.
        self.assertTrue(
            services.reports.is_blocked_between(str(self.bob.id), str(self.alice.id))
        )
        self.assertFalse(services.matches.are_matched(str(self.alice.id), str(self.bob.id)))


class DiscoveryFlowTests(TestCase):
    def setUp(self):
        self.seeker = make_member("seeker@test.zynora.app", "seeker", gender="man")
        services.profiles.update_preferences(
            str(self.seeker.id), interested_in=["woman"],
            with_photos_only=False, max_distance_km=200,
        )
        self.candidates = [
            make_member(f"cand{i}@test.zynora.app", f"cand{i}", gender="woman")
            for i in range(4)
        ]

    def test_feed_returns_scored_candidates(self):
        feed = services.discovery.get_feed(str(self.seeker.id), limit=10, refresh=True)
        self.assertTrue(feed)
        card = feed[0]
        self.assertIn("score", card)
        self.assertIn("score_label", card)
        self.assertIn("distance_label", card)
        self.assertNotIn(str(self.seeker.id), [c["user"]["id"] for c in feed])

    def test_swiped_candidates_leave_the_feed(self):
        feed = services.discovery.get_feed(str(self.seeker.id), limit=10, refresh=True)
        target = feed[0]["user"]["id"]

        services.likes.swipe(str(self.seeker.id), target, "pass")
        refreshed = services.discovery.get_feed(str(self.seeker.id), limit=10, refresh=True)
        self.assertNotIn(target, [c["user"]["id"] for c in refreshed])

    def test_blocked_members_never_appear(self):
        feed = services.discovery.get_feed(str(self.seeker.id), limit=10, refresh=True)
        target = feed[0]["user"]["id"]

        services.reports.block_user(str(self.seeker.id), target, "test")
        refreshed = services.discovery.get_feed(str(self.seeker.id), limit=10, refresh=True)
        self.assertNotIn(target, [c["user"]["id"] for c in refreshed])


class EntitlementTests(TestCase):
    def setUp(self):
        from apps.subscriptions.models import Plan

        self.user = make_member("payer@test.zynora.app", "payer")
        Plan.objects.update_or_create(
            code="free",
            defaults={"name": "Free", "price": 0, "duration_days": 36500,
                      "is_default": True, "daily_likes": 20, "entitlements": []},
        )
        Plan.objects.update_or_create(
            code="gold",
            defaults={"name": "Gold", "price": 19900, "duration_days": 30,
                      "daily_likes": None,
                      "entitlements": ["see_who_likes_you", "unlimited_likes"]},
        )

    def test_free_plan_lacks_premium_entitlements(self):
        self.assertFalse(
            services.subscriptions.has_entitlement(str(self.user.id), "see_who_likes_you")
        )
        limits = services.subscriptions.get_quota_limits(str(self.user.id))
        self.assertEqual(limits["daily_likes"], 20)

    def test_payment_success_grants_the_plan(self):
        """PAYMENT_SUCCEEDED is what upgrades a member — nothing else."""
        from apps.common.events import Event, publish

        publish(Event.PAYMENT_SUCCEEDED, {
            "user_id": str(self.user.id), "purpose": "subscription",
            "plan_code": "gold", "amount": 19900, "currency": "TZS",
            "payment_id": None, "reference": "TEST-1",
        })

        self.assertTrue(
            services.subscriptions.has_entitlement(str(self.user.id), "see_who_likes_you")
        )
        self.assertIsNone(
            services.subscriptions.get_quota_limits(str(self.user.id))["daily_likes"]
        )


class ModerationTests(TestCase):
    def test_scam_language_is_blocked(self):
        from apps.moderation.models import BannedTerm

        BannedTerm.objects.create(term="send me money", action="block", severity="critical")
        verdict = services.moderation.screen_text("Please send me money for a ticket")
        self.assertTrue(verdict["blocked"])

    def test_ordinary_message_passes(self):
        verdict = services.moderation.screen_text("Hey, how was your weekend?")
        self.assertFalse(verdict["blocked"])
        self.assertFalse(verdict["flagged"])

    def test_contact_details_are_flagged_but_not_blocked(self):
        verdict = services.moderation.screen_text("WhatsApp me on +255712345678")
        self.assertTrue(verdict["flagged"])
        self.assertFalse(verdict["blocked"])


class PageRenderTests(TestCase):
    """Every server-rendered page must return 200 for a signed-in member."""

    def setUp(self):
        self.user = make_member("pages@test.zynora.app", "pages")
        self.client.force_login(self.user)

    def test_public_pages(self):
        for name in ("common:landing", "common:about", "common:safety",
                     "common:terms", "common:privacy"):
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_member_pages(self):
        for name in ("discovery:feed", "discovery:admirers", "matches:list",
                     "chat:inbox", "notifications:inbox", "profiles:me",
                     "profiles:edit", "profiles:photos", "profiles:preferences",
                     "profiles:viewers", "subscriptions:plans", "subscriptions:mine",
                     "verification:home", "reports:blocked", "reports:support",
                     "security:my_security", "audit:my_activity", "accounts:overview",
                     "accounts:details", "accounts:settings", "accounts:devices",
                     "likes:sent", "likes:quota", "payments:history",
                     "recommendation:sets", "recommendation:top_picks"):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200, f"{name} returned {response.status_code}")

    def test_api_root_and_health(self):
        self.assertEqual(self.client.get("/api/v1/").status_code, 200)
        self.assertIn(self.client.get("/api/v1/health/").status_code, (200, 503))

    def test_me_summary_aggregates_every_service(self):
        response = self.client.get("/api/v1/me/summary/")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        for key in ("user", "account", "subscription", "quota", "verification", "badges"):
            self.assertIn(key, data)
