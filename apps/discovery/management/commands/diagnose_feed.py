"""Explain why a member's Discover feed looks the way it does.

    python manage.py diagnose_feed alice@example.com
    python manage.py diagnose_feed --platform      # health of the whole pool

Written because "my feed is empty" is otherwise a guessing game: the pool is
built from four exclusions and then narrowed by five hard filters, and any one
of them can empty it.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.common.registry import services

User = get_user_model()


class Command(BaseCommand):
    help = "Diagnose an empty or short Discover feed."

    def add_arguments(self, parser):
        parser.add_argument("email", nargs="?", help="Member to diagnose.")
        parser.add_argument("--platform", action="store_true",
                            help="Show pool health across the whole platform.")

    def handle(self, *args, **options):
        if options["platform"] or not options["email"]:
            self._platform()
        if options["email"]:
            self._member(options["email"])

    # ------------------------------------------------------------------
    def _platform(self):
        self.stdout.write(self.style.MIGRATE_HEADING("\nPlatform pool health\n"))

        # Profile-side numbers come from the profiles contract, not its tables.
        profiles = services.profiles.pool_stats()

        total = User.objects.count()
        checks = [
            ("total accounts", total, None),
            ("active", User.objects.filter(is_active=True, status="active").count(),
             "inactive accounts never appear"),
            ("email verified", User.objects.filter(is_email_verified=True).count(),
             "dateable() requires a verified email"),
            ("onboarding complete", User.objects.filter(has_completed_onboarding=True).count(),
             "dateable() requires a finished profile"),
            ("-> dateable pool", User.objects.dateable().count(), None),
            ("profiles visible", profiles["visible"], None),
            ("with a gender set", profiles["with_gender"],
             "no gender means every gender filter rejects them"),
            ("with a location", profiles["with_location"],
             "no location means distance ranking is neutral"),
            ("with an approved photo", profiles["with_photos"],
             "with_photos_only is on by default"),
        ]

        for label, count, note in checks:
            share = f"{count / total * 100:5.1f}%" if total else "    —"
            self.stdout.write(f"  {label:<26} {count:>5}  {share}")
            if note and total and count < total * 0.8:
                self.stdout.write(self.style.WARNING(f"      ↳ {note}"))

        no_photos = profiles["without_photos"]
        if no_photos:
            self.stdout.write(self.style.WARNING(
                f"\n  {no_photos} member(s) have no approved photo and are invisible "
                "in Discover.\n  Fix with:  python manage.py backfill_photos"
            ))
        self.stdout.write("")

    def _member(self, email):
        user = User.objects.filter(email__iexact=email).first()
        if not user:
            raise CommandError(f"No account with email '{email}'.")

        user_id = str(user.id)
        self.stdout.write(self.style.MIGRATE_HEADING(f"\nFeed diagnosis: {user.email}\n"))

        # 1. Is the seeker themselves eligible?
        self.stdout.write("  Seeker eligibility")
        for label, ok in (
            ("active", user.is_active and user.status == "active"),
            ("email verified", user.is_email_verified),
            ("onboarded", user.has_completed_onboarding),
        ):
            mark = self.style.SUCCESS("✓") if ok else self.style.ERROR("✗")
            self.stdout.write(f"    {mark} {label}")

        profile = services.profiles.get_profile(user_id) or {}
        self.stdout.write(f"    photos: {profile.get('photo_count', 0)}  "
                          f"completion: {profile.get('completion_score', 0)}%  "
                          f"visible: {profile.get('is_visible')}")

        # 2. What are they filtering on?
        prefs = services.profiles.get_preferences(user_id) or {}
        self.stdout.write("\n  Filters")
        self.stdout.write(f"    looking for      {prefs.get('interested_in') or 'anyone'}")
        self.stdout.write(f"    age range        {prefs.get('min_age')}–{prefs.get('max_age')}")
        self.stdout.write(f"    max distance     {prefs.get('max_distance_km')} km")
        self.stdout.write(f"    photos only      {prefs.get('with_photos_only')}")
        self.stdout.write(f"    verified only    {prefs.get('verified_only')}")
        self.stdout.write(f"    global search    {prefs.get('show_me_globally')}")

        # 3. Pool construction
        excluded = {user_id}
        swiped = services.likes.get_swiped_ids(user_id)
        matched = services.matches.get_matched_user_ids(user_id)
        blocked = services.reports.get_blocked_user_ids(user_id)
        excluded.update(swiped, matched, blocked)

        pool = services.accounts.list_dateable_ids(exclude_ids=list(excluded), limit=400)
        self.stdout.write("\n  Pool")
        self.stdout.write(f"    dateable overall {User.objects.dateable().count()}")
        self.stdout.write(f"    already swiped   {len(swiped)}")
        self.stdout.write(f"    already matched  {len(matched)}")
        self.stdout.write(f"    blocked either way {len(blocked)}")
        self.stdout.write(f"    -> candidates    {len(pool)}")

        # 4. Ranking and rejections
        feed = services.discovery.get_feed(user_id, limit=20, refresh=True)
        diagnostics = services.matching.last_run_diagnostics(user_id) or {}

        self.stdout.write("\n  Ranking")
        self.stdout.write(f"    considered       {diagnostics.get('considered', 0)}")
        self.stdout.write(f"    passed filters   {diagnostics.get('scored', 0)}")
        self.stdout.write(f"    top score        {diagnostics.get('top_score', 0)}%")

        rejected = diagnostics.get("filtered_out") or {}
        if rejected:
            self.stdout.write("    rejected because:")
            for reason, count in sorted(rejected.items(), key=lambda kv: -kv[1]):
                self.stdout.write(f"      {count:>4}  {reason}")

        if feed:
            self.stdout.write(self.style.SUCCESS(f"\n  ✓ Feed returns {len(feed)} card(s)"))
            for card in feed[:5]:
                self.stdout.write(
                    f"      {card['user']['display_name']:<12} "
                    f"{card['score']:>3}%  {card['distance_label']}"
                )
        else:
            self.stdout.write(self.style.ERROR("\n  ✗ Feed is empty"))
            explanation = services.discovery.explain_empty_feed(user_id)
            self.stdout.write(f"    {explanation['headline']}")
            for reason in explanation["reasons"]:
                self.stdout.write(f"      · {reason['text']}")
        self.stdout.write("")
