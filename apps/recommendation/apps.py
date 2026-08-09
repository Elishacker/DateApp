from django.apps import AppConfig


class RecommendationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.recommendation"
    verbose_name = "Recommendation (ranked picks service)"

    def ready(self):
        from . import signals  # noqa: F401
