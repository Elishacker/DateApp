"""Seed a working demo dataset.

    python manage.py seed_demo --users 40

Creates the interest catalogue, subscription plans, banned-term list, demo
members with profiles and photos-less but complete data, plus some likes and
matches so every screen has something to show.

Everything goes through the service contracts, which means running this command
also exercises the event bus end to end.
"""
import random
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.common.constants import (
    DEFAULT_INTERESTS,
    ChildrenStatus,
    EducationLevel,
    Gender,
    LifestyleChoice,
    RelationshipGoal,
)
from apps.common.registry import services
from apps.common.utils import slugify_unique

User = get_user_model()

FIRST_NAMES_A = ["Amina", "Neema", "Zawadi", "Halima", "Sara", "Grace", "Rehema",
                 "Latifa", "Asha", "Fatuma", "Joyce", "Naomi", "Upendo", "Salma"]
FIRST_NAMES_B = ["Juma", "Baraka", "Emmanuel", "Hassan", "Daniel", "Rashid",
                 "Peter", "Ibrahim", "Joseph", "Musa", "Elias", "Frank", "Yusuf"]

CITIES = [
    ("Dar es Salaam", "Tanzania", -6.7924, 39.2083),
    ("Arusha", "Tanzania", -3.3869, 36.6830),
    ("Mwanza", "Tanzania", -2.5164, 32.9175),
    ("Dodoma", "Tanzania", -6.1630, 35.7516),
    ("Zanzibar City", "Tanzania", -6.1659, 39.2026),
    ("Nairobi", "Kenya", -1.2921, 36.8219),
    ("Mombasa", "Kenya", -4.0435, 39.6682),
    ("Kampala", "Uganda", 0.3476, 32.5825),
]

HEADLINES = [
    "Coffee first, conversation second",
    "Looking for someone to explore the coast with",
    "Engineer by day, terrible cook by night",
    "Ask me about my last hiking trip",
    "Serious about football, not much else",
    "Here for real conversations",
    "Weekend markets and long drives",
    "Trying to read more and scroll less",
]

BIOS = [
    "I work in tech, spend most weekends outdoors, and I'm genuinely looking for "
    "something that lasts. Tell me the best meal you've had this month.",
    "Born in Mwanza, living in Dar. I like early mornings, long walks and people "
    "who laugh easily. Not here for games.",
    "Teacher, runner, and a reliably bad dancer. Looking for someone kind who has "
    "their own thing going on.",
    "I split my time between work and the coast. Big on honesty, small talk not so "
    "much. Let's skip to the real conversation.",
]

PLANS = [
    {
        "code": "free", "name": "Free", "tagline": "Get started",
        "price": 0, "duration_days": 36500, "is_default": True, "sort_order": 0,
        "entitlements": [],
        "daily_likes": 20, "daily_super_likes": 10, "daily_rewinds": 0,
        "daily_messages": 200, "monthly_boosts": 0,
        "description": "Everything you need to start meeting people.",
    },
    {
        "code": "plus", "name": "Plus", "tagline": "See who likes you",
        "price": 9900, "duration_days": 30, "sort_order": 1,
        # Seeing your admirers is what subscribing buys, at every paid tier.
        "entitlements": ["unlimited_likes", "rewind", "no_ads", "see_who_likes_you"],
        "daily_likes": None, "daily_super_likes": 3, "daily_rewinds": 5,
        "daily_messages": None, "monthly_boosts": 0,
        "description": "See everyone who liked you, unlimited likes, and undo a swipe.",
    },
    {
        "code": "gold", "name": "Gold", "tagline": "Filter exactly who you meet",
        "price": 19900, "duration_days": 30, "sort_order": 2,
        "is_featured": True, "badge_color": "#f59e0b",
        "entitlements": ["unlimited_likes", "rewind", "no_ads", "see_who_likes_you",
                         "see_profile_viewers", "advanced_filters", "media_messages",
                         "read_receipts"],
        "daily_likes": None, "daily_super_likes": 5, "daily_rewinds": None,
        "daily_messages": None, "monthly_boosts": 1,
        "description": "See everyone who liked you and filter exactly who you meet.",
    },
    {
        "code": "premium", "name": "Premium", "tagline": "Everything",
        "price": 34900, "duration_days": 30, "sort_order": 3, "trial_days": 7,
        "badge_color": "#7c3aed",
        "entitlements": ["unlimited_likes", "rewind", "no_ads", "see_who_likes_you",
                         "see_profile_viewers", "advanced_filters", "media_messages",
                         "read_receipts", "unlimited_messages", "boost", "incognito",
                         "priority_support"],
        "daily_likes": None, "daily_super_likes": 10, "daily_rewinds": None,
        "daily_messages": None, "monthly_boosts": 4,
        "description": "Every feature, including incognito browsing and monthly boosts.",
    },
]

BANNED_TERMS = [
    ("send me money", "scam", "block", "critical"),
    ("western union", "scam", "block", "critical"),
    ("bitcoin wallet", "scam", "block", "high"),
    ("investment opportunity", "scam", "flag", "high"),
    ("sugar daddy", "solicitation", "flag", "medium"),
    ("onlyfans", "solicitation", "flag", "high"),
    ("cashapp", "solicitation", "flag", "medium"),
]


class Command(BaseCommand):
    help = "Seed interests, plans, moderation terms and demo members."

    def add_arguments(self, parser):
        parser.add_argument("--users", type=int, default=30,
                            help="How many demo members to create.")
        parser.add_argument("--password", default="ZynoraDemo2026!",
                            help="Password shared by every demo account.")
        parser.add_argument("--skip-users", action="store_true",
                            help="Seed reference data only.")

    @transaction.atomic
    def handle(self, *args, **options):
        random.seed(42)  # reproducible demo data

        self.stdout.write(self.style.MIGRATE_HEADING("\nSeeding Zynora\n"))
        self._seed_interests()
        self._seed_plans()
        self._seed_banned_terms()

        if not options["skip_users"]:
            members = self._seed_members(options["users"], options["password"])
            self._seed_photos()
            self._seed_engagement(members)
            self._report(options["password"])

        self.stdout.write(self.style.SUCCESS("\n✓ Seed complete.\n"))

    # ------------------------------------------------------------------
    def _seed_interests(self):
        from apps.profiles.models import Interest

        created = 0
        for name, category in DEFAULT_INTERESTS:
            _, made = Interest.objects.get_or_create(
                name=name,
                defaults={"slug": slugify_unique(name, Interest), "category": category},
            )
            created += int(made)
        self.stdout.write(f"  interests    {created} created "
                          f"({Interest.objects.count()} total)")

    def _seed_plans(self):
        from apps.subscriptions.models import Plan

        for spec in PLANS:
            Plan.objects.update_or_create(code=spec["code"], defaults=spec)
        self.stdout.write(f"  plans        {Plan.objects.count()} configured")

    def _seed_banned_terms(self):
        from apps.moderation.models import BannedTerm

        for term, category, action, severity in BANNED_TERMS:
            BannedTerm.objects.get_or_create(
                term=term,
                defaults={"category": category, "action": action, "severity": severity},
            )
        self.stdout.write(f"  safety       {BannedTerm.objects.count()} banned terms")

    def _seed_members(self, count, password):
        from apps.profiles.models import Interest

        interests = list(Interest.objects.values_list("id", flat=True))
        members = []

        for index in range(count):
            is_woman = index % 2 == 0
            first = random.choice(FIRST_NAMES_A if is_woman else FIRST_NAMES_B)
            username = f"{first.lower()}{index:02d}"
            email = f"{username}@demo.zynora.app"

            if User.objects.filter(email=email).exists():
                members.append(User.objects.get(email=email))
                continue

            age = random.randint(21, 41)
            record = services.accounts.create_account(
                email=email, username=username, password=password,
                first_name=first,
                date_of_birth=date.today() - timedelta(days=age * 365 + random.randint(0, 364)),
                accepted_terms=True,
            )
            user = User.objects.get(id=record["id"])

            # Demo accounts skip email verification so they are immediately usable.
            user.is_email_verified = True
            user.status = "active"
            user.has_completed_onboarding = True
            user.last_active_at = timezone.now() - timedelta(hours=random.randint(0, 72))
            user.is_online = random.random() < 0.18
            # A share of demo members carry a photo-verified badge so the
            # verified filters and badges have something to act on.
            user.is_phone_verified = random.random() < 0.5
            user.is_photo_verified = random.random() < 0.3
            user.save()
            user.recompute_verification_level()

            city, country, lat, lon = random.choice(CITIES)
            services.profiles.update_profile(
                str(user.id),
                gender=Gender.WOMAN if is_woman else Gender.MAN,
                headline=random.choice(HEADLINES),
                bio=random.choice(BIOS),
                job_title=random.choice(["Software engineer", "Teacher", "Nurse",
                                         "Accountant", "Designer", "Entrepreneur",
                                         "Analyst", "Consultant"]),
                education_level=random.choice(list(EducationLevel.values)),
                relationship_goal=random.choice(list(RelationshipGoal.values)),
                smoking=random.choice(list(LifestyleChoice.values)),
                drinking=random.choice(list(LifestyleChoice.values)),
                children=random.choice(list(ChildrenStatus.values)),
                languages=random.sample(["English", "Swahili", "French"], k=2),
                interests=[str(i) for i in random.sample(interests, k=min(6, len(interests)))],
            )
            services.profiles.set_location(
                str(user.id),
                latitude=lat + random.uniform(-0.12, 0.12),
                longitude=lon + random.uniform(-0.12, 0.12),
                city=city, country=country,
            )
            services.profiles.update_preferences(
                str(user.id),
                interested_in=[Gender.MAN if is_woman else Gender.WOMAN],
                min_age=max(18, age - 8), max_age=age + 8,
                max_distance_km=random.choice([50, 100, 200]),
                with_photos_only=False,   # demo accounts have no photos
            )
            members.append(user)

        self.stdout.write(f"  members      {len(members)} demo accounts")
        return members

    def _seed_photos(self):
        """Members without a photo are invisible in Discover by design, so a
        seeded system must give everyone one or the feed comes back empty."""
        from django.core.management import call_command

        call_command("backfill_photos", verbosity=0)
        self.stdout.write("  photos       generated for every member")

    def _seed_engagement(self, members):
        """Create likes and a handful of mutual matches."""
        if len(members) < 4:
            return

        likes = matches = 0
        for sender in members[: len(members) // 2]:
            targets = random.sample(members, k=min(5, len(members)))
            for target in targets:
                if target.id == sender.id:
                    continue
                try:
                    result = services.likes.swipe(
                        str(sender.id), str(target.id),
                        random.choices(["like", "pass"], weights=[3, 1])[0],
                    )
                    likes += 1
                    if result and result.get("matched"):
                        matches += 1
                except Exception:  # noqa: BLE001 - quota or duplicate, both fine
                    continue

        self.stdout.write(f"  engagement   {likes} swipes, {matches} matches")

    def _report(self, password):
        self.stdout.write(self.style.MIGRATE_HEADING("\nDemo credentials"))
        for user in User.objects.filter(email__endswith="@demo.zynora.app")[:3]:
            self.stdout.write(f"  {user.email}  /  {password}")
        self.stdout.write("  (every demo account shares this password)")
