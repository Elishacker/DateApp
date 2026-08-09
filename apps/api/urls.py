"""REST gateway.

Composes every module's ``api_urls`` under ``/api/v1/``. The gateway knows only
each module's name and mount point — never its models or serializers. When a
module is extracted, its block here is replaced with a proxy (or deleted, if the
client is pointed straight at the new service) and nothing else changes.
"""
from django.urls import include, path

from . import views

app_name = "api"


def _module(prefix, name):
    return path(prefix, include((f"apps.{name}.api_urls", name), namespace=name))


urlpatterns = [
    # Gateway meta
    path("", views.APIRootView.as_view(), name="root"),
    path("health/", views.APIHealthView.as_view(), name="health"),
    path("me/summary/", views.MeSummaryView.as_view(), name="me_summary"),

    # Identity
    _module("auth/", "authentication"),
    _module("accounts/", "accounts"),

    # Member data
    _module("profiles/", "profiles"),
    _module("onboarding/", "onboarding"),

    # Engagement
    _module("discovery/", "discovery"),
    _module("likes/", "likes"),
    _module("matches/", "matches"),
    _module("matching/", "matching"),
    _module("recommendations/", "recommendation"),

    # Communication
    _module("chat/", "chat"),
    _module("notifications/", "notifications"),

    # Money
    _module("subscriptions/", "subscriptions"),
    _module("payments/", "payments"),

    # Trust and safety
    _module("verification/", "verification"),
    _module("moderation/", "moderation"),
    _module("reports/", "reports"),

    # Operations
    _module("analytics/", "analytics"),
]
