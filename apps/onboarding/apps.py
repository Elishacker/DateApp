from django.apps import AppConfig


class OnboardingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.onboarding"
    verbose_name = "Onboarding (signup wizard service)"

    def ready(self):
        from . import signals  # noqa: F401
