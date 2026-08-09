from django.apps import AppConfig


class ReportsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.reports"
    verbose_name = "Reports (abuse and safety service)"

    def ready(self):
        from . import signals  # noqa: F401
