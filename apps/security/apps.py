from django.apps import AppConfig


class SecurityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.security"
    verbose_name = "Security (threat detection service)"

    def ready(self):
        from . import signals  # noqa: F401
