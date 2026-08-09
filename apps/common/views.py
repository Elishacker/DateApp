"""Public marketing pages and shared error handlers."""
from django.shortcuts import render
from django.views.generic import TemplateView


class LandingView(TemplateView):
    template_name = "common/landing.html"

    def get_context_data(self, **kwargs):
        # Plans are owned by the subscriptions service — fetched through its
        # contract, never by importing its models.
        from apps.common.registry import services

        context = super().get_context_data(**kwargs)
        context["plans"] = services.subscriptions.list_public_plans()
        context["highlights"] = [
            ("Compatibility that means something",
             "Our engine weighs interests, lifestyle, goals and distance — not just photos."),
            ("Verified people, not bots",
             "Photo, phone and ID verification with automated fake-account detection."),
            ("Security built in from day one",
             "Device tracking, login anomaly alerts and end-to-end audit logging."),
        ]
        return context


class AboutView(TemplateView):
    template_name = "common/about.html"


class SafetyView(TemplateView):
    template_name = "common/safety.html"


class TermsView(TemplateView):
    template_name = "common/legal.html"
    extra_context = {"document": "terms", "title": "Terms of Service"}


class PrivacyView(TemplateView):
    template_name = "common/legal.html"
    extra_context = {"document": "privacy", "title": "Privacy Policy"}


class OfflineView(TemplateView):
    """Fallback the service worker serves when a navigation fetch fails."""

    template_name = "pwa/offline.html"


class ServiceWorkerView(TemplateView):
    """A service worker's default scope is the directory it's served from,
    so this must stay mounted at /sw.js (not /static/sw.js) to control the
    whole origin. Rendered as a template so {% static %} in it resolves to
    WhiteNoise's hashed filenames, keeping the precache list self-invalidating.
    """

    template_name = "pwa/service-worker.js"
    content_type = "application/javascript"


class HealthView(TemplateView):
    """Liveness probe used by Docker/Kubernetes."""

    def get(self, request, *args, **kwargs):
        from django.db import connection
        from django.http import JsonResponse

        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            database = "ok"
        except Exception as exc:  # pragma: no cover - infrastructure failure
            database = f"error: {exc}"

        healthy = database == "ok"
        return JsonResponse(
            {"status": "healthy" if healthy else "degraded", "database": database},
            status=200 if healthy else 503,
        )


def bad_request(request, exception=None):
    return render(request, "errors/400.html", status=400)


def permission_denied(request, exception=None):
    return render(request, "errors/403.html", status=403)


def page_not_found(request, exception=None):
    return render(request, "errors/404.html", status=404)


def server_error(request):
    return render(request, "errors/500.html", status=500)
