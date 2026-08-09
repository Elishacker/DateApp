from django.apps import AppConfig


class DiscoveryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.discovery"
    verbose_name = "Discovery (feed service)"

    def ready(self):
        from . import signals  # noqa: F401
