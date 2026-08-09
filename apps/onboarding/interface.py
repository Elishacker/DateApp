"""Public contract of the onboarding service."""
from apps.common.interface import ModuleInterface

from .models import OnboardingProgress
from .services import OnboardingService


class OnboardingInterface(ModuleInterface):
    name = "onboarding"
    depends_on = ("accounts", "profiles")

    def get_state(self, user_id):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.filter(id=user_id).first()
        return OnboardingService.state(user) if user else None

    def is_complete(self, user_id):
        return OnboardingProgress.objects.filter(user_id=user_id, is_complete=True).exists()

    def current_step(self, user_id):
        progress = OnboardingProgress.objects.filter(user_id=user_id).first()
        return int(progress.current_step) if progress else 1

    def start(self, user_id):
        """Idempotent — called on USER_REGISTERED."""
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.filter(id=user_id).first()
        if not user:
            return False
        OnboardingService.get_progress(user)
        return True

    def completion_stats(self):
        """Funnel counts for the analytics dashboard."""
        total = OnboardingProgress.objects.count()
        complete = OnboardingProgress.objects.filter(is_complete=True).count()
        by_step = {}
        for row in OnboardingProgress.objects.values("current_step").distinct():
            step = row["current_step"]
            by_step[str(step)] = OnboardingProgress.objects.filter(current_step=step).count()
        return {
            "total": total,
            "complete": complete,
            "completion_rate": round(complete / total * 100, 1) if total else 0.0,
            "by_step": by_step,
        }


service = OnboardingInterface()
