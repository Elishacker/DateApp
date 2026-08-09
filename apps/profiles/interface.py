"""Public contract of the profiles service.

Discovery, matching, chat and moderation all read profile data exclusively
through these methods. ``get_match_payloads`` in particular is designed for the
matching engine: one query, no ORM objects, everything the scorer needs.
"""
from apps.common.interface import ModuleInterface

from .models import Interest, MatchPreference, Profile, ProfilePhoto, ProfileView
from .services import PhotoService, PreferenceService, ProfileService


class ProfilesInterface(ModuleInterface):
    name = "profiles"
    depends_on = ("accounts", "moderation")

    # ---- single profile reads ----------------------------------------------
    def get_profile(self, user_id):
        profile = Profile.objects.filter(user_id=user_id).prefetch_related("interests").first()
        return self._serialize(profile) if profile else None

    def get_public_card(self, user_id, viewer_id=None):
        """The trimmed shape rendered on a discovery card."""
        profile = Profile.objects.filter(user_id=user_id).prefetch_related("interests").first()
        if not profile:
            return None
        return {
            "user_id": str(profile.user_id),
            "headline": profile.headline,
            "bio": profile.bio,
            "city": profile.city,
            "region": profile.region,
            "country": profile.country,
            "location_label": profile.location_label,
            "region_label": profile.region_label,
            "job_title": profile.job_title,
            "school": profile.school,
            "relationship_goal": profile.relationship_goal,
            "interests": profile.interest_names(),
            "photos": self.get_photo_urls(user_id),
            "primary_photo_url": profile.primary_photo_url,
            "completion_score": profile.completion_score,
            "is_boosted": profile.is_boosted,
        }

    def exists(self, user_id):
        return Profile.objects.filter(user_id=user_id).exists()

    def is_visible(self, user_id):
        return Profile.objects.filter(user_id=user_id, is_visible=True).exists()

    def get_completion(self, user_id):
        profile = Profile.objects.filter(user_id=user_id).first()
        return profile.completion_score if profile else 0

    def get_location(self, user_id):
        profile = Profile.objects.filter(user_id=user_id).only(
            "latitude", "longitude", "city", "country"
        ).first()
        if not profile or not profile.has_location:
            return None
        return {
            "latitude": float(profile.latitude),
            "longitude": float(profile.longitude),
            "city": profile.city,
            "country": profile.country,
        }

    def get_photo_urls(self, user_id, approved_only=True):
        qs = ProfilePhoto.objects.filter(user_id=user_id)
        if approved_only:
            qs = qs.filter(moderation_status=ProfilePhoto.ModerationStatus.APPROVED)
        return [p.url for p in qs.order_by("-is_primary", "position") if p.url]

    # ---- bulk reads (matching / discovery hot path) -------------------------
    def get_match_payloads(self, user_ids):
        """Everything the compatibility scorer needs, keyed by user id.

        One query with prefetching — this is the method that keeps the matching
        engine from N+1ing across a candidate pool.
        """
        rows = (
            Profile.objects.filter(user_id__in=list(user_ids))
            .select_related("user")
            .prefetch_related("interests")
        )
        payloads = {}
        for profile in rows:
            payloads[str(profile.user_id)] = {
                "user_id": str(profile.user_id),
                "age": profile.age,
                "gender": profile.gender,
                "latitude": float(profile.latitude) if profile.latitude is not None else None,
                "longitude": float(profile.longitude) if profile.longitude is not None else None,
                "city": profile.city,
                "country": profile.country,
                "interests": profile.interest_names(),
                "relationship_goal": profile.relationship_goal,
                "education_level": profile.education_level,
                "languages": list(profile.languages or []),
                "religion": profile.religion,
                "smoking": profile.smoking,
                "drinking": profile.drinking,
                "children": profile.children,
                "completion_score": profile.completion_score,
                "photo_count": profile.photo_count,
                "primary_photo_url": profile.primary_photo_url,
                "is_visible": profile.is_visible,
                "is_boosted": profile.is_boosted,
                "headline": profile.headline,
            }
        return payloads

    def search_ids(self, query, exclude_ids=(), limit=200, fields=None):
        """Match a query against the profile fields this module owns.

        ``fields`` narrows the search: any of ``region``, ``country``, ``job``,
        ``interests``, ``about``. Omit it to search all of them.
        """
        from django.db.models import Q

        query = (query or "").strip()
        if len(query) < 2:
            return []

        clauses = {
            "region": Q(city__icontains=query) | Q(region__icontains=query),
            "country": Q(country__icontains=query),
            "job": Q(job_title__icontains=query) | Q(company__icontains=query)
                   | Q(school__icontains=query),
            "interests": Q(interests__name__icontains=query),
            "about": Q(headline__icontains=query) | Q(bio__icontains=query),
        }
        selected = [clauses[f] for f in (fields or clauses) if f in clauses]
        if not selected:
            return []

        combined = selected[0]
        for clause in selected[1:]:
            combined |= clause

        return [
            str(pk) for pk in Profile.objects.filter(is_visible=True)
            .filter(combined)
            .exclude(user_id__in=list(exclude_ids))
            .values_list("user_id", flat=True)
            .distinct()[:limit]
        ]

    def search_facets(self):
        """Distinct values worth offering as search suggestions."""
        return {
            "countries": sorted(
                c for c in Profile.objects.exclude(country="")
                .values_list("country", flat=True).distinct() if c
            ),
            "regions": sorted(
                r for r in Profile.objects.exclude(city="")
                .values_list("city", flat=True).distinct() if r
            )[:40],
        }

    def pool_stats(self):
        """Profile-side health of the candidate pool.

        Exposed so diagnostics can report why feeds are thin without reading
        this module's tables.
        """
        return {
            "profiles": Profile.objects.count(),
            "visible": Profile.objects.filter(is_visible=True).count(),
            "with_gender": Profile.objects.exclude(gender="").count(),
            "with_location": Profile.objects.filter(latitude__isnull=False).count(),
            "with_photos": Profile.objects.filter(photo_count__gt=0).count(),
            "without_photos": Profile.objects.filter(photo_count=0).count(),
        }

    def filter_visible_ids(self, user_ids):
        return [
            str(pk) for pk in Profile.objects.filter(
                user_id__in=list(user_ids), is_visible=True
            ).values_list("user_id", flat=True)
        ]

    # ---- preferences --------------------------------------------------------
    def get_preferences(self, user_id):
        preference = MatchPreference.objects.filter(user_id=user_id).first()
        return preference.as_filter_dict() if preference else None

    def update_preferences(self, user_id, **fields):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.filter(id=user_id).first()
        if not user:
            return None
        return PreferenceService.update(user, **fields).as_filter_dict()

    # ---- writes used by other services --------------------------------------
    def update_profile(self, user_id, **fields):
        """Partial profile update. ``interests`` accepts UUIDs or names."""
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.filter(id=user_id).first()
        if not user:
            return None
        return self._serialize(ProfileService.update(user, **fields))

    def set_location(self, user_id, *, latitude, longitude, city="", region="", country=""):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.filter(id=user_id).first()
        if not user:
            return None
        profile = ProfileService.update_location(
            user, latitude=latitude, longitude=longitude,
            city=city, region=region, country=country,
        )
        return {"city": profile.city, "country": profile.country,
                "latitude": float(profile.latitude), "longitude": float(profile.longitude)}

    def apply_photo_moderation(self, photo_id, approved, note=""):
        return PhotoService.apply_moderation(photo_id, approved, note)

    def set_visibility(self, user_id, visible):
        Profile.objects.filter(user_id=user_id).update(is_visible=visible)
        return visible

    def apply_boost(self, user_id, until):
        """Called by subscriptions when a Boost entitlement is consumed."""
        Profile.objects.filter(user_id=user_id).update(is_boosted_until=until)
        return True

    def record_view(self, viewer_id, viewed_id, source="discovery"):
        from django.contrib.auth import get_user_model

        viewer = get_user_model().objects.filter(id=viewer_id).first()
        if not viewer:
            return False
        return bool(ProfileService.record_view(viewer, viewed_id, source))

    def get_viewer_ids(self, user_id, limit=50):
        return [str(pk) for pk in ProfileService.viewers_of(user_id, limit)]

    def count_views(self, user_id, since=None):
        qs = ProfileView.objects.filter(viewed_id=user_id)
        if since:
            qs = qs.filter(created_at__gte=since)
        return qs.count()

    # ---- catalogue ----------------------------------------------------------
    def list_interests(self, category=None):
        qs = Interest.objects.filter(is_active=True)
        if category:
            qs = qs.filter(category=category)
        return [
            {"id": str(i.id), "name": i.name, "slug": i.slug,
             "category": i.category, "emoji": i.emoji}
            for i in qs
        ]

    def ensure_profile(self, user_id):
        """Idempotent bootstrap, called by the onboarding service on signup."""
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.filter(id=user_id).first()
        if not user:
            return False
        ProfileService.get_or_create(user)
        return True

    # ---- helpers ------------------------------------------------------------
    @staticmethod
    def _serialize(profile):
        return {
            "user_id": str(profile.user_id),
            "headline": profile.headline,
            "bio": profile.bio,
            "gender": profile.gender,
            "pronouns": profile.pronouns,
            "height_cm": profile.height_cm,
            "job_title": profile.job_title,
            "company": profile.company,
            "education_level": profile.education_level,
            "school": profile.school,
            "smoking": profile.smoking,
            "drinking": profile.drinking,
            "exercise": profile.exercise,
            "children": profile.children,
            "religion": profile.religion,
            "languages": list(profile.languages or []),
            "relationship_goal": profile.relationship_goal,
            "interests": profile.interest_names(),
            "city": profile.city,
            "region": profile.region,
            "country": profile.country,
            "latitude": float(profile.latitude) if profile.latitude is not None else None,
            "longitude": float(profile.longitude) if profile.longitude is not None else None,
            "completion_score": profile.completion_score,
            "photo_count": profile.photo_count,
            "primary_photo_url": profile.primary_photo_url,
            "is_visible": profile.is_visible,
            "is_boosted": profile.is_boosted,
        }


service = ProfilesInterface()
