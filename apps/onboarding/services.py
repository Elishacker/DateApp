"""Onboarding orchestration.

Each step validates its input, then forwards it to the service that owns that
data. Onboarding is a coordinator, not a data owner.
"""
import logging

from apps.common.events import Event, publish
from apps.common.exceptions import ValidationError
from apps.common.registry import services

from .models import OnboardingProgress, OnboardingStep

logger = logging.getLogger(__name__)

#: Presentation metadata for each step, consumed by the view (never the template).
STEP_META = {
    OnboardingStep.WELCOME: {
        "key": "welcome", "title": "Welcome to Zynora",
        "subtitle": "Six quick steps and you're in.", "skippable": False,
    },
    OnboardingStep.IDENTITY: {
        "key": "identity", "title": "About you",
        "subtitle": "The basics people will see first.", "skippable": False,
    },
    OnboardingStep.PHOTOS: {
        "key": "photos", "title": "Add your photos",
        "subtitle": "Profiles with three or more photos get far more matches.",
        "skippable": False,
    },
    OnboardingStep.INTERESTS: {
        "key": "interests", "title": "What are you into?",
        "subtitle": "Pick at least three — they drive your matches.", "skippable": False,
    },
    OnboardingStep.PREFERENCES: {
        "key": "preferences", "title": "Who are you looking for?",
        "subtitle": "You can change this any time.", "skippable": False,
    },
    OnboardingStep.LOCATION: {
        "key": "location", "title": "Where are you?",
        "subtitle": "We only ever show your city, never your exact position.",
        "skippable": True,
    },
}


class OnboardingService:
    @staticmethod
    def get_progress(user):
        progress, _ = OnboardingProgress.objects.get_or_create(user=user)
        return progress

    @staticmethod
    def state(user):
        """Render-ready wizard state. The view passes this straight to context."""
        progress = OnboardingService.get_progress(user)
        step = OnboardingStep(progress.current_step)
        meta = STEP_META.get(step, STEP_META[OnboardingStep.WELCOME])

        steps = []
        for candidate in OnboardingStep:
            if candidate == OnboardingStep.DONE:
                continue
            steps.append({
                "number": int(candidate),
                "label": candidate.label,
                "is_done": int(candidate) in progress.completed_steps,
                "is_current": int(candidate) == int(progress.current_step),
            })

        return {
            "step_number": int(step),
            "step_key": meta["key"],
            "title": meta["title"],
            "subtitle": meta["subtitle"],
            "skippable": meta["skippable"],
            "percent_complete": progress.percent_complete,
            "total_steps": progress.total_steps,
            "steps": steps,
            "is_complete": progress.is_complete,
        }

    # ---- step handlers ------------------------------------------------------
    @staticmethod
    def submit_identity(user, *, gender, headline="", bio="", relationship_goal="",
                        job_title="", school=""):
        if not gender:
            raise ValidationError("Tell us how you identify.", field="gender")
        services.profiles.ensure_profile(str(user.id))
        services.profiles.update_profile(
            str(user.id), gender=gender, headline=headline, bio=bio,
            relationship_goal=relationship_goal, job_title=job_title, school=school,
        )
        return OnboardingService._advance(user, OnboardingStep.IDENTITY)

    @staticmethod
    def submit_photos(user):
        if services.profiles.get_profile(str(user.id))["photo_count"] < 1:
            raise ValidationError("Add at least one photo to continue.")
        return OnboardingService._advance(user, OnboardingStep.PHOTOS)

    @staticmethod
    def submit_interests(user, interest_ids):
        if len(interest_ids or []) < 3:
            raise ValidationError("Pick at least three interests.")
        services.profiles.update_profile(str(user.id), interests=list(interest_ids))
        return OnboardingService._advance(user, OnboardingStep.INTERESTS)

    @staticmethod
    def submit_preferences(user, **fields):
        services.profiles.update_preferences(str(user.id), **fields)
        return OnboardingService._advance(user, OnboardingStep.PREFERENCES)

    @staticmethod
    def submit_location(user, *, latitude=None, longitude=None, city="", country=""):
        if latitude is not None and longitude is not None:
            services.profiles.set_location(
                str(user.id), latitude=latitude, longitude=longitude,
                city=city, country=country,
            )
        return OnboardingService._advance(user, OnboardingStep.LOCATION)

    @staticmethod
    def skip_step(user, step):
        progress = OnboardingService.get_progress(user)
        meta = STEP_META.get(OnboardingStep(step))
        if not meta or not meta["skippable"]:
            raise ValidationError("This step cannot be skipped.")
        if step not in progress.skipped_steps:
            progress.skipped_steps = [*progress.skipped_steps, step]
            progress.save(update_fields=["skipped_steps"])
        return OnboardingService._advance(user, step)

    @staticmethod
    def _advance(user, step):
        progress = OnboardingService.get_progress(user)
        progress.mark_step_done(int(step))
        services.accounts.set_onboarding_step(str(user.id), progress.current_step)

        if progress.is_complete:
            services.accounts.mark_onboarding_complete(str(user.id), progress.current_step)
            publish(Event.ONBOARDING_COMPLETED, {
                "user_id": str(user.id),
                "skipped_steps": progress.skipped_steps,
            }, actor_id=user.id)
            logger.info("onboarding complete for %s", user.id)
        return progress
