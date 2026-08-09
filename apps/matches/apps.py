from django.apps import AppConfig


class MatchesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.matches"
    verbose_name = "Matches (connection service)"

    def ready(self):
        from . import signals  # noqa: F401
