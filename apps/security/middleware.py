"""Security middleware: headers, device fingerprinting and rate limiting."""
import logging

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render

from apps.common.utils import client_ip

logger = logging.getLogger("zynora.security")


class SecurityHeadersMixin:
    """Shared CSP construction so dev and prod differ only in strictness."""

    @staticmethod
    def content_security_policy():
        # 'unsafe-inline' is confined to styles; scripts are file-based only,
        # which is what the MVT split buys us.
        directives = [
            "default-src 'self'",
            "script-src 'self'",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data: blob: https:",
            "media-src 'self' blob:",
            "font-src 'self' data:",
            "connect-src 'self' ws: wss:",
            "frame-ancestors 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "object-src 'none'",
        ]
        if not settings.DEBUG:
            directives.append("upgrade-insecure-requests")
        return "; ".join(directives)


class SecurityHeadersMiddleware(SecurityHeadersMixin):
    """Applies defence-in-depth response headers to every request."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.csp = self.content_security_policy()

    def __call__(self, request):
        response = self.get_response(request)

        response.setdefault("Content-Security-Policy", self.csp)
        response.setdefault("X-Content-Type-Options", "nosniff")
        response.setdefault("X-Frame-Options", "DENY")
        response.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.setdefault(
            "Permissions-Policy",
            "geolocation=(self), microphone=(self), camera=(self), payment=()",
        )
        response.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.setdefault("X-Permitted-Cross-Domain-Policies", "none")

        # Never let a browser or proxy cache an authenticated page.
        if getattr(request, "user", None) and request.user.is_authenticated:
            response.setdefault("Cache-Control", "no-store, private")
        return response


class DeviceFingerprintMiddleware:
    """Derives a device fingerprint and pins the session to it.

    A session cookie replayed from a different browser produces a different
    fingerprint; that mismatch is recorded as a possible hijack.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from .services import FingerprintService

        fingerprint = FingerprintService.compute(request)
        request.device_fingerprint = fingerprint

        if hasattr(request, "session"):
            stored = request.session.get("device_fingerprint")
            if not stored:
                request.session["device_fingerprint"] = fingerprint
            elif stored != fingerprint and request.user.is_authenticated:
                self._flag_mismatch(request, stored, fingerprint)
                request.session["device_fingerprint"] = fingerprint

        return self.get_response(request)

    @staticmethod
    def _flag_mismatch(request, expected, actual):
        from .models import SecurityEvent
        from .services import AnomalyService

        # Returns None when an identical alert was raised recently.
        logger.debug("fingerprint mismatch user=%s", request.user.id)
        AnomalyService.record(
            SecurityEvent.Kind.SESSION_HIJACK,
            user_id=request.user.id,
            severity="high",
            description="Session used from a different browser signature.",
            request=request,
            metadata={"expected": expected[:16], "actual": actual[:16]},
        )


class RateLimitMiddleware:
    """Global request ceiling per IP, plus a stricter one for auth endpoints."""

    #: Paths exempt from the global limit (health checks, provider callbacks).
    EXEMPT_PREFIXES = ("/health/", "/payments/webhook/", "/static/", "/media/")
    #: Paths that get the tighter auth limit.
    SENSITIVE_PREFIXES = ("/auth/login", "/auth/register", "/auth/password",
                          "/api/v1/auth/")

    def __init__(self, get_response):
        self.get_response = get_response
        self.global_limit, self.global_window = settings.ZYNORA["GLOBAL_RATE_LIMIT"]
        self.auth_limit, self.auth_window = settings.ZYNORA["LOGIN_RATE_LIMIT"]

    def __call__(self, request):
        from .services import RateLimitService, ReputationService

        path = request.path
        if path.startswith(self.EXEMPT_PREFIXES):
            return self.get_response(request)

        ip = client_ip(request)
        if ip and ReputationService.is_blocked(ip):
            logger.warning("blocked IP %s hit %s", ip, path)
            return self._deny(request, "Your network has been temporarily blocked.")

        if path.startswith(self.SENSITIVE_PREFIXES) and request.method == "POST":
            allowed, _ = RateLimitService.check(
                "auth", ip, self.auth_limit, self.auth_window, request
            )
            if not allowed:
                return self._deny(request, "Too many attempts. Please wait a few minutes.")

        allowed, _ = RateLimitService.check(
            "global", ip, self.global_limit, self.global_window, request
        )
        if not allowed:
            return self._deny(request, "You're going a bit fast. Please slow down.")

        return self.get_response(request)

    @staticmethod
    def _deny(request, message):
        if request.path.startswith("/api/") or request.headers.get(
            "X-Requested-With"
        ) == "XMLHttpRequest":
            return JsonResponse(
                {"success": False, "error": {"code": "rate_limited", "message": message}},
                status=429,
            )
        return render(request, "errors/429.html", {"message": message}, status=429)
