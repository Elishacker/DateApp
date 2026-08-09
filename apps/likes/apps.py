from django.apps import AppConfig


class LikesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.likes"
    verbose_name = "Likes (swipe intent service)"

    def ready(self):
        from . import signals  # noqa: F401
