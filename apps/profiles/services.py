"""Profile business logic."""
import logging

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.common.events import Event, publish
from apps.common.exceptions import NotFound, QuotaExceeded, ValidationError
from apps.common.registry import services
from apps.common.utils import slugify_unique

from .models import Interest, MatchPreference, Profile, ProfilePhoto, ProfileView

logger = logging.getLogger(__name__)

MAX_PHOTOS = 9
#: Coordinates are rounded before storage so an exact home address is never held.
LOCATION_PRECISION = 3  # ~110 m


class ProfileService:
    @staticmethod
    def get_or_create(user):
        profile, created = Profile.objects.get_or_create(user=user)
        if created:
            MatchPreference.objects.get_or_create(user=user)
        return profile

    @staticmethod
    def get(user_id):
        profile = Profile.objects.filter(user_id=user_id).first()
        if not profile:
            raise NotFound("That profile does not exist.")
        return profile

    @staticmethod
    @transaction.atomic
    def update(user, **fields):
        profile = ProfileService.get_or_create(user)

        interests = fields.pop("interests", None)
        editable = {
            f.name for f in Profile._meta.fields
        } - {"user", "created_at", "updated_at", "completion_score",
             "photo_count", "primary_photo_url", "is_boosted_until"}

        changed = []
        for key, value in fields.items():
            if key in editable:
                setattr(profile, key, value)
                changed.append(key)

        if changed:
            profile.full_clean(exclude=[f for f in editable if f not in changed])
            profile.save(update_fields=changed + ["updated_at"])

        if interests is not None:
            ProfileService.set_interests(profile, interests)

        profile.refresh_completion()
        publish(Event.PROFILE_UPDATED, {
            "user_id": str(user.id),
            "fields": changed,
            "completion_score": profile.completion_score,
            "avatar_url": profile.primary_photo_url,
        }, actor_id=user.id)
        return profile

    @staticmethod
    def set_interests(profile, interest_ids_or_names):
        """Accepts UUIDs or plain names; unknown names are created on the fly."""
        resolved = []
        for item in interest_ids_or_names or []:
            interest = (
                Interest.objects.filter(id=item).first()
                if _looks_like_uuid(item)
                else Interest.objects.filter(name__iexact=str(item).strip()).first()
            )
            if not interest and not _looks_like_uuid(item):
                name = str(item).strip()[:60]
                if name:
                    interest = Interest.objects.create(
                        name=name, slug=slugify_unique(name, Interest)
                    )
            if interest:
                resolved.append(interest)

        if len(resolved) > 15:
            raise ValidationError("Choose up to 15 interests.")

        previous = set(profile.interests.values_list("id", flat=True))
        profile.interests.set(resolved)
        current = {i.id for i in resolved}

        Interest.objects.filter(id__in=current - previous).update(usage_count=F("usage_count") + 1)
        Interest.objects.filter(id__in=previous - current, usage_count__gt=0).update(
            usage_count=F("usage_count") - 1
        )
        return resolved

    @staticmethod
    def update_location(user, *, latitude, longitude, city="", region="", country=""):
        profile = ProfileService.get_or_create(user)
        # Quantise through Decimal, not round(float): a rounded float still
        # carries its full binary expansion into a DecimalField.
        profile.latitude = _coarse(latitude)
        profile.longitude = _coarse(longitude)
        profile.city = city or profile.city
        profile.region = region or profile.region
        profile.country = country or profile.country
        profile.location_updated_at = timezone.now()
        profile.full_clean(exclude=["user"])
        profile.save(update_fields=[
            "latitude", "longitude", "city", "region", "country",
            "location_updated_at", "updated_at",
        ])
        profile.refresh_completion()
        return profile

    @staticmethod
    def set_visibility(user, visible):
        Profile.objects.filter(user=user).update(is_visible=visible)
        return visible

    @staticmethod
    def record_view(viewer, viewed_id, source="discovery"):
        """Deduplicated to one row per viewer/viewed pair per hour."""
        if str(viewer.id) == str(viewed_id):
            return None
        cutoff = timezone.now() - timezone.timedelta(hours=1)
        if ProfileView.objects.filter(
            viewer=viewer, viewed_id=viewed_id, created_at__gte=cutoff
        ).exists():
            return None
        return ProfileView.objects.create(viewer=viewer, viewed_id=viewed_id, source=source)

    @staticmethod
    def viewers_of(user_id, limit=50):
        return (
            ProfileView.objects.filter(viewed_id=user_id)
            .order_by("-created_at")
            .values_list("viewer_id", flat=True)
            .distinct()[:limit]
        )


class PhotoService:
    @staticmethod
    @transaction.atomic
    def upload(user, image, caption="", make_primary=False):
        profile = ProfileService.get_or_create(user)
        count = ProfilePhoto.objects.filter(user=user).count()
        if count >= MAX_PHOTOS:
            raise QuotaExceeded(f"You can upload at most {MAX_PHOTOS} photos.")

        photo = ProfilePhoto.objects.create(
            user=user,
            image=image,
            caption=caption[:140],
            position=count,
            is_primary=make_primary or count == 0,
            file_size=getattr(image, "size", 0),
        )
        if photo.is_primary:
            ProfilePhoto.objects.filter(user=user).exclude(pk=photo.pk).update(is_primary=False)

        PhotoService._sync_profile(profile)

        # Moderation is asynchronous — the photo is pending until it clears.
        try:
            services.moderation.queue_image_review(
                owner_id=str(user.id), object_type="profile_photo",
                object_id=str(photo.id), url=photo.url,
            )
        except Exception:  # noqa: BLE001
            logger.exception("could not queue photo %s for moderation", photo.id)

        publish(Event.PHOTO_UPLOADED, {
            "user_id": str(user.id),
            "photo_id": str(photo.id),
            "avatar_url": profile.primary_photo_url,
        }, actor_id=user.id)
        return photo

    @staticmethod
    @transaction.atomic
    def delete(user, photo_id):
        photo = ProfilePhoto.objects.filter(id=photo_id, user=user).first()
        if not photo:
            raise NotFound("Photo not found.")
        was_primary = photo.is_primary
        photo.delete()

        remaining = ProfilePhoto.objects.filter(user=user).order_by("position")
        for index, item in enumerate(remaining):
            if item.position != index:
                item.position = index
                item.save(update_fields=["position"])
        if was_primary and remaining.exists():
            first = remaining.first()
            first.is_primary = True
            first.save(update_fields=["is_primary"])

        PhotoService._sync_profile(ProfileService.get_or_create(user))
        return True

    @staticmethod
    @transaction.atomic
    def set_primary(user, photo_id):
        photo = ProfilePhoto.objects.filter(id=photo_id, user=user).first()
        if not photo:
            raise NotFound("Photo not found.")
        if not photo.is_public:
            raise ValidationError("That photo is still being reviewed.")
        ProfilePhoto.objects.filter(user=user).update(is_primary=False)
        photo.is_primary = True
        photo.save(update_fields=["is_primary"])
        PhotoService._sync_profile(ProfileService.get_or_create(user))
        return photo

    @staticmethod
    @transaction.atomic
    def reorder(user, ordered_ids):
        photos = {str(p.id): p for p in ProfilePhoto.objects.filter(user=user)}
        for index, photo_id in enumerate(ordered_ids):
            photo = photos.get(str(photo_id))
            if photo and photo.position != index:
                photo.position = index
                photo.save(update_fields=["position"])
        return True

    @staticmethod
    def apply_moderation(photo_id, approved, note=""):
        """Called by the moderation service through this module's interface."""
        photo = ProfilePhoto.objects.filter(id=photo_id).first()
        if not photo:
            return False
        photo.moderation_status = (
            ProfilePhoto.ModerationStatus.APPROVED if approved
            else ProfilePhoto.ModerationStatus.REJECTED
        )
        photo.moderation_note = note[:255]
        photo.moderated_at = timezone.now()
        photo.save(update_fields=["moderation_status", "moderation_note", "moderated_at"])

        profile = Profile.objects.filter(user_id=photo.user_id).first()
        if profile:
            PhotoService._sync_profile(profile)
        return True

    @staticmethod
    def _sync_profile(profile):
        """Recompute the denormalised photo counters after any gallery change."""
        approved = ProfilePhoto.objects.filter(
            user_id=profile.user_id,
            moderation_status=ProfilePhoto.ModerationStatus.APPROVED,
        ).order_by("-is_primary", "position")

        profile.photo_count = approved.count()
        primary = approved.first()
        profile.primary_photo_url = primary.url if primary else ""
        profile.save(update_fields=["photo_count", "primary_photo_url", "updated_at"])
        profile.refresh_completion()

        # Keep the accounts read model in step.
        publish(Event.PROFILE_UPDATED, {
            "user_id": str(profile.user_id),
            "fields": ["primary_photo_url"],
            "avatar_url": profile.primary_photo_url,
            "completion_score": profile.completion_score,
        }, actor_id=profile.user_id)


class PreferenceService:
    @staticmethod
    def get_or_create(user):
        preference, _ = MatchPreference.objects.get_or_create(user=user)
        return preference

    @staticmethod
    def update(user, **fields):
        preference = PreferenceService.get_or_create(user)
        editable = {f.name for f in MatchPreference._meta.fields} - {"user", "created_at", "updated_at"}
        changed = []
        for key, value in fields.items():
            if key in editable:
                setattr(preference, key, value)
                changed.append(key)
        if changed:
            preference.full_clean(exclude=["user"])
            preference.save(update_fields=changed + ["updated_at"])
            publish(Event.PREFERENCES_UPDATED, {
                "user_id": str(user.id), "fields": changed,
            }, actor_id=user.id)
        return preference


def _coarse(value):
    """Round a coordinate to ``LOCATION_PRECISION`` places as an exact Decimal.

    Deliberate privacy measure: three places is roughly 110 m, which is enough
    for distance ranking and far too coarse to identify a home address.
    """
    from decimal import ROUND_HALF_UP, Decimal

    quantum = Decimal(1).scaleb(-LOCATION_PRECISION)  # e.g. Decimal("0.001")
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)


def _looks_like_uuid(value):
    import uuid as _uuid

    try:
        _uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False
