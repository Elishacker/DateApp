"""Search, and the rule that a like does not hide someone.

Both behaviours are easy to regress by "tidying up" the exclusion list, so they
are pinned here.
"""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.common.registry import services

User = get_user_model()


def make_member(email, *, gender="woman", city="Arusha", region="Arusha",
                country="Tanzania", job="Nurse", age=28, lat=-3.38, lon=36.68):
    handle = email.split("@")[0].replace("-", "_")
    record = services.accounts.create_account(
        email=email, username=handle, password="ZynoraTest2026!",
        first_name=handle.title(),
        date_of_birth=date.today() - timedelta(days=age * 365),
        accepted_terms=True,
    )
    user = User.objects.get(id=record["id"])
    user.is_email_verified = True
    user.status = "active"
    user.has_completed_onboarding = True
    user.save()

    services.profiles.update_profile(
        str(user.id), gender=gender, job_title=job,
        headline="Test headline", bio="A bio long enough to count for completion.",
        interests=["Hiking", "Music"],
    )
    services.profiles.set_location(
        str(user.id), latitude=lat, longitude=lon,
        city=city, region=region, country=country,
    )
    services.profiles.update_preferences(
        str(user.id), with_photos_only=False, interested_in=[],
        min_age=18, max_age=99, max_distance_km=500,
    )
    return user


class LikeVisibilityTests(TestCase):
    def setUp(self):
        self.seeker = make_member("seeker@like.test", gender="man")
        self.target = make_member("target@like.test", gender="woman")

    def test_liking_keeps_the_person_in_the_feed(self):
        services.discovery.invalidate_feed(str(self.seeker.id))
        before = services.discovery.get_feed(str(self.seeker.id), limit=20, refresh=True)
        self.assertIn(str(self.target.id), [c["user"]["id"] for c in before])

        services.likes.swipe(str(self.seeker.id), str(self.target.id), "like")
        services.discovery.invalidate_feed(str(self.seeker.id))
        after = services.discovery.get_feed(str(self.seeker.id), limit=20, refresh=True)

        card = next((c for c in after if c["user"]["id"] == str(self.target.id)), None)
        self.assertIsNotNone(card, "a liked profile must stay in the feed")
        self.assertTrue(card["has_liked"])
        self.assertEqual(card["liked_kind"], "like")

    def test_the_like_still_reaches_the_recipient(self):
        services.likes.swipe(str(self.seeker.id), str(self.target.id), "like")

        self.assertIn(str(self.seeker.id),
                      services.likes.get_admirer_ids(str(self.target.id)))
        self.assertGreater(
            services.notifications.get_unread_count(str(self.target.id)), 0
        )

    def test_passing_does_hide_the_person(self):
        services.likes.swipe(str(self.seeker.id), str(self.target.id), "pass")
        services.discovery.invalidate_feed(str(self.seeker.id))
        after = services.discovery.get_feed(str(self.seeker.id), limit=20, refresh=True)
        self.assertNotIn(str(self.target.id), [c["user"]["id"] for c in after])

    def test_liking_twice_is_rejected_but_upgrading_is_allowed(self):
        from apps.common.exceptions import ValidationError

        services.likes.swipe(str(self.seeker.id), str(self.target.id), "like")

        with self.assertRaises(ValidationError):
            services.likes.swipe(str(self.seeker.id), str(self.target.id), "like")

        # like -> super like is a deliberate upgrade, not a duplicate.
        result = services.likes.swipe(str(self.seeker.id), str(self.target.id), "super_like")
        self.assertIsNotNone(result)

    def test_matching_does_remove_the_card(self):
        services.likes.swipe(str(self.target.id), str(self.seeker.id), "like")
        services.likes.swipe(str(self.seeker.id), str(self.target.id), "like")

        self.assertTrue(services.matches.are_matched(str(self.seeker.id), str(self.target.id)))
        services.discovery.invalidate_feed(str(self.seeker.id))
        after = services.discovery.get_feed(str(self.seeker.id), limit=20, refresh=True)
        self.assertNotIn(str(self.target.id), [c["user"]["id"] for c in after],
                         "matches belong on the Matches tab, not in Discover")


class SearchTests(TestCase):
    def setUp(self):
        self.seeker = make_member("finder@search.test", gender="man")
        self.nurse = make_member(
            "grace@search.test", city="Mwanza", region="Mwanza",
            country="Tanzania", job="Paediatric Nurse",
        )
        self.analyst = make_member(
            "joyce@search.test", city="Nairobi", region="Nairobi",
            country="Kenya", job="Data Analyst", lat=-1.29, lon=36.82,
        )

    def _ids(self, **kwargs):
        outcome = services.discovery.search(str(self.seeker.id), **kwargs)
        return [c["user"]["id"] for c in outcome["results"]]

    def test_search_by_name(self):
        self.assertIn(str(self.nurse.id), self._ids(query="Grace"))

    def test_search_by_region(self):
        found = self._ids(query="Nairobi")
        self.assertIn(str(self.analyst.id), found)
        self.assertNotIn(str(self.nurse.id), found)

    def test_search_by_country(self):
        self.assertIn(str(self.analyst.id), self._ids(query="Kenya", scope="country"))

    def test_search_by_job_title(self):
        found = self._ids(query="Nurse", scope="job")
        self.assertIn(str(self.nurse.id), found)
        self.assertNotIn(str(self.analyst.id), found)

    def test_search_by_interest(self):
        self.assertIn(str(self.nurse.id), self._ids(query="Hiking", scope="interests"))

    def test_search_never_returns_the_searcher(self):
        self.assertNotIn(str(self.seeker.id), self._ids(query="Finder"))

    def test_search_excludes_blocked_members(self):
        services.reports.block_user(str(self.seeker.id), str(self.nurse.id), "test")
        self.assertNotIn(str(self.nurse.id), self._ids(query="Grace"))

    def test_short_queries_are_rejected(self):
        outcome = services.discovery.search(str(self.seeker.id), query="a")
        self.assertEqual(outcome["results"], [])
        self.assertIn("two characters", outcome["message"])

    def test_search_ignores_preferences_by_default(self):
        """Looking someone up is a different intent from browsing a feed."""
        services.profiles.update_preferences(
            str(self.seeker.id), interested_in=["man"], max_distance_km=1
        )
        # Both targets are women and far away, yet a name search still finds them.
        self.assertIn(str(self.nurse.id), self._ids(query="Grace"))

        strict = self._ids(query="Grace", respect_preferences=True)
        self.assertNotIn(str(self.nurse.id), strict)

    def test_search_page_renders(self):
        self.client.force_login(self.seeker)
        response = self.client.get(reverse("discovery:search"), {"q": "Nairobi"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Joyce")
