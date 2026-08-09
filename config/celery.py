"""Celery application and the platform-wide periodic schedule."""
import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = Celery("zynora")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    "expire-subscriptions": {
        "task": "apps.subscriptions.tasks.expire_due_subscriptions",
        "schedule": crontab(minute=0, hour="*"),
    },
    "reset-daily-quotas": {
        "task": "apps.subscriptions.tasks.reset_daily_quotas",
        "schedule": crontab(minute=5, hour=0),
    },
    "refresh-recommendations": {
        "task": "apps.recommendation.tasks.refresh_all_top_picks",
        "schedule": crontab(minute=30, hour=3),
    },
    "rollup-daily-metrics": {
        "task": "apps.analytics.tasks.rollup_daily_metrics",
        "schedule": crontab(minute=15, hour=1),
    },
    "purge-stale-devices": {
        "task": "apps.security.tasks.purge_stale_devices",
        "schedule": crontab(minute=0, hour=4, day_of_week=1),
    },
    "sweep-expired-tokens": {
        "task": "apps.authentication.tasks.sweep_expired_tokens",
        "schedule": crontab(minute=0, hour="*/6"),
    },
}


@app.task(bind=True)
def debug_task(self):
    return f"request: {self.request!r}"
