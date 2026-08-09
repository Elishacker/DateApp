"""Root URL configuration.

Every module mounts its own URLConf under its own prefix — nothing here knows
what a module contains. Removing a module from ``INSTALLED_APPS`` and deleting
its line below is the entire "extraction" step at the routing layer.
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.api import internal

admin.site.site_header = "Zynora Administration"
admin.site.site_title = "Zynora Admin"
admin.site.index_title = "Platform control centre"


def _module(prefix, name):
    return path(prefix, include((f"apps.{name}.urls", name), namespace=name))


urlpatterns = [
    path("admin/", admin.site.urls),

    # Server-rendered surface, one prefix per service module
    _module("", "common"),
    _module("auth/", "authentication"),
    _module("account/", "accounts"),
    _module("onboarding/", "onboarding"),
    _module("profile/", "profiles"),
    _module("discover/", "discovery"),
    _module("likes/", "likes"),
    _module("matches/", "matches"),
    _module("chat/", "chat"),
    _module("notifications/", "notifications"),
    _module("subscriptions/", "subscriptions"),
    _module("payments/", "payments"),
    _module("verification/", "verification"),
    _module("reports/", "reports"),
    _module("moderation/", "moderation"),
    _module("analytics/", "analytics"),
    _module("security/", "security"),
    _module("audit/", "audit"),
    _module("matching/", "matching"),
    _module("recommendations/", "recommendation"),

    # Unified REST gateway
    path("api/v1/", include(("apps.api.urls", "api"), namespace="api")),

    # Service-to-service RPC. Disabled unless INTERNAL_SERVICE_TOKEN is set,
    # and never exposed on a public listener in production.
    path("internal/<str:service_name>/<str:method>/", internal.dispatch, name="internal_rpc"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler400 = "apps.common.views.bad_request"
handler403 = "apps.common.views.permission_denied"
handler404 = "apps.common.views.page_not_found"
handler500 = "apps.common.views.server_error"
