"""Role-based access control tests.

The point of these is blunt: prove that an ordinary member cannot see or reach
any staff surface, and that each staff role reaches exactly what its
capabilities allow — no more.
"""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.accounts.roles import ROLE_CAPABILITIES, capabilities_for
from apps.common.constants import Capability
from apps.common.registry import services

User = get_user_model()

#: Every staff URL, with the capability that should guard it.
STAFF_URLS = [
    ("moderation:queue", Capability.MODERATE_CONTENT),
    ("moderation:trust", Capability.MODERATE_CONTENT),
    ("reports:queue", Capability.REVIEW_REPORTS),
    ("verification:queue", Capability.REVIEW_VERIFICATION),
    ("analytics:dashboard", Capability.VIEW_ANALYTICS),
    ("security:dashboard", Capability.VIEW_SECURITY_OPS),
    ("audit:trail", Capability.VIEW_AUDIT_TRAIL),
]


def make_user(email, role="member", *, superuser=False):
    handle = email.split("@")[0].replace("-", "_")
    record = services.accounts.create_account(
        email=email, username=handle, password="ZynoraTest2026!",
        first_name=handle.replace("_", " ").title(),
        date_of_birth=date.today() - timedelta(days=28 * 365),
        accepted_terms=True,
    )
    user = User.objects.get(id=record["id"])
    user.is_email_verified = True
    user.status = "active"
    user.has_completed_onboarding = True
    user.is_superuser = superuser
    user.save()
    if role != "member":
        services.accounts.set_role(str(user.id), role)
        user.refresh_from_db()
    return user


class CapabilityMatrixTests(TestCase):
    def test_member_has_no_capabilities(self):
        member = make_user("member@roles.test")
        self.assertEqual(services.accounts.get_capabilities(str(member.id)), [])
        self.assertFalse(services.accounts.is_staff_member(str(member.id)))

    def test_each_role_gets_exactly_its_declared_capabilities(self):
        for role in ROLE_CAPABILITIES:
            with self.subTest(role=role):
                user = make_user(f"{role}@matrix.test", role=role)
                granted = set(services.accounts.get_capabilities(str(user.id)))
                self.assertEqual(granted, capabilities_for(role))

    def test_superuser_gets_everything(self):
        root = make_user("root@roles.test", superuser=True)
        self.assertEqual(
            set(services.accounts.get_capabilities(str(root.id))), set(Capability)
        )

    def test_setting_a_role_syncs_django_admin_access(self):
        user = make_user("promote@roles.test")
        self.assertFalse(user.is_staff)

        services.accounts.set_role(str(user.id), "admin")
        user.refresh_from_db()
        self.assertTrue(user.is_staff, "admin should reach the Django admin")

        services.accounts.set_role(str(user.id), "moderator")
        user.refresh_from_db()
        self.assertFalse(user.is_staff, "moderator must not reach the Django admin")

    def test_role_change_is_audited(self):
        user = make_user("audited@roles.test")
        services.accounts.set_role(str(user.id), "moderator")
        actions = [e["action"] for e in services.audit.activity_about(str(user.id))]
        self.assertIn("accounts.role.changed", actions)


class StaffPageAccessTests(TestCase):
    def test_member_is_refused_every_staff_page(self):
        member = make_user("nosy@roles.test")
        self.client.force_login(member)
        for url_name, _ in STAFF_URLS:
            with self.subTest(page=url_name):
                response = self.client.get(reverse(url_name))
                self.assertEqual(response.status_code, 403,
                                 f"{url_name} must be forbidden to a member")

    def test_member_sidebar_contains_no_staff_links(self):
        member = make_user("plain@roles.test")
        self.client.force_login(member)
        html = self.client.get(reverse("discovery:feed")).content.decode()

        for label in ("Moderation", "Security ops", "Audit trail", "Analytics"):
            self.assertNotIn(label, html, f"'{label}' leaked into a member's sidebar")
        self.assertNotIn("sidebar-heading", html)

    def test_each_role_reaches_only_what_it_may(self):
        for role in ("support", "analyst", "moderator", "admin"):
            user = make_user(f"{role}@pages.test", role=role)
            held = capabilities_for(role)
            self.client.force_login(user)

            for url_name, capability in STAFF_URLS:
                expected = 200 if capability in held else 403
                with self.subTest(role=role, page=url_name):
                    response = self.client.get(reverse(url_name))
                    self.assertEqual(
                        response.status_code, expected,
                        f"{role} on {url_name}: expected {expected}, "
                        f"got {response.status_code}",
                    )
            self.client.logout()

    def test_sidebar_shows_only_permitted_entries(self):
        analyst = make_user("analyst@sidebar.test", role="analyst")
        self.client.force_login(analyst)
        html = self.client.get(reverse("discovery:feed")).content.decode()

        self.assertIn("Analytics", html)
        for label in ("Moderation", "Reports", "Security ops", "Audit trail"):
            self.assertNotIn(label, html,
                             f"analyst should not see '{label}'")

    def test_anonymous_is_redirected_not_403(self):
        response = self.client.get(reverse("analytics:dashboard"))
        self.assertIn(response.status_code, (301, 302))


class StaffApiAccessTests(TestCase):
    ENDPOINTS = [
        ("/api/v1/moderation/queue/", Capability.MODERATE_CONTENT),
        ("/api/v1/reports/queue/", Capability.REVIEW_REPORTS),
        ("/api/v1/verification/queue/", Capability.REVIEW_VERIFICATION),
        ("/api/v1/analytics/", Capability.VIEW_ANALYTICS),
    ]

    def test_member_is_refused_every_staff_endpoint(self):
        member = make_user("api-member@roles.test")
        self.client.force_login(member)
        for path, _ in self.ENDPOINTS:
            with self.subTest(endpoint=path):
                self.assertEqual(self.client.get(path).status_code, 403)

    def test_roles_reach_only_their_endpoints(self):
        for role in ("analyst", "moderator", "admin"):
            user = make_user(f"{role}@api.test", role=role)
            held = capabilities_for(role)
            self.client.force_login(user)
            for path, capability in self.ENDPOINTS:
                expected = 200 if capability in held else 403
                with self.subTest(role=role, endpoint=path):
                    self.assertEqual(self.client.get(path).status_code, expected)
            self.client.logout()


class StaffNavigationTests(TestCase):
    def test_navigation_is_empty_for_members(self):
        member = make_user("nav-member@roles.test")
        self.assertEqual(services.accounts.get_staff_navigation(str(member.id)), [])

    def test_navigation_matches_capabilities(self):
        moderator = make_user("nav-mod@roles.test", role="moderator")
        labels = {
            item["label"]
            for item in services.accounts.get_staff_navigation(str(moderator.id))
        }
        self.assertEqual(labels, {"Moderation", "Reports", "Verifications"})

    def test_every_navigation_target_resolves(self):
        from django.urls import reverse as django_reverse

        from apps.accounts.roles import STAFF_NAVIGATION

        for url_name, _, _, _ in STAFF_NAVIGATION:
            with self.subTest(url=url_name):
                django_reverse(url_name)  # raises if the route is missing
