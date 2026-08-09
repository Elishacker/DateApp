"""Anomaly detection, rate limiting and IP reputation."""
import hashlib
import logging

from django.conf import settings
from django.utils import timezone

from apps.common.events import Event, publish
from apps.common.registry import services
from apps.common.services import CacheService
from apps.common.utils import client_ip, haversine_km, user_agent

from .models import AnomalySeverity, IPReputation, RateLimitBreach, SecurityEvent

logger = logging.getLogger("zynora.security")

#: Faster than this between two logins implies the account is shared or stolen.
IMPOSSIBLE_TRAVEL_KMH = 900


class FingerprintService:
    """Stable-ish device identifier from request characteristics.

    Not a security boundary on its own — it is a *signal*. It changes when the
    browser changes, which is exactly what makes a new value worth alerting on.
    """

    @staticmethod
    def compute(request):
        parts = [
            user_agent(request),
            request.META.get("HTTP_ACCEPT_LANGUAGE", ""),
            request.META.get("HTTP_ACCEPT_ENCODING", ""),
            request.META.get("HTTP_SEC_CH_UA", ""),
            request.META.get("HTTP_SEC_CH_UA_PLATFORM", ""),
        ]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:64]


class RateLimitService:
    """Fixed-window counters in the cache. Cheap, and good enough at this size."""

    @staticmethod
    def check(scope, identifier, limit, window_seconds, request=None):
        """Return ``(allowed, hits)``; records a breach the first time it trips."""
        hits = CacheService.incr("ratelimit", scope, identifier, ttl=window_seconds)
        if hits <= limit:
            return True, hits

        if hits == limit + 1:  # record once per window, not on every request
            RateLimitBreach.objects.create(
                scope=scope, identifier=str(identifier)[:191],
                ip_address=client_ip(request) if request else None,
                path=request.path[:255] if request else "",
                limit=limit, window_seconds=window_seconds, hits=hits,
            )
            ip = client_ip(request) if request else None
            if ip:
                ReputationService.penalise(ip, 5, "rate limit exceeded")
            logger.warning("rate limit tripped scope=%s id=%s", scope, identifier)
        return False, hits

    @staticmethod
    def reset(scope, identifier):
        CacheService.delete("ratelimit", scope, identifier)


class ReputationService:
    @staticmethod
    def get(ip):
        record, _ = IPReputation.objects.get_or_create(ip_address=ip)
        return record

    @staticmethod
    def penalise(ip, points, note=""):
        if not ip:
            return None
        record = ReputationService.get(ip)
        return record.penalise(points, note)

    @staticmethod
    def is_blocked(ip):
        if not ip:
            return False
        cached = CacheService.get("security", "ipblock", ip)
        if cached is not None:
            return bool(cached)
        record = IPReputation.objects.filter(ip_address=ip).first()
        blocked = bool(record and record.is_currently_blocked)
        CacheService.set("security", "ipblock", ip, value=int(blocked), ttl=300)
        return blocked

    @staticmethod
    def touch(ip):
        if ip:
            IPReputation.objects.filter(ip_address=ip).update(last_seen_at=timezone.now())


class AnomalyService:
    """Turns login telemetry into risk decisions."""

    @staticmethod
    def evaluate_login(user_id, *, ip=None, device_fingerprint="",
                       user_agent_string="", device_is_new=False):
        """Score a successful login and raise events for anything unusual."""
        signals = []
        risk = 0

        if device_is_new:
            signals.append(("new device", 25, SecurityEvent.Kind.NEW_DEVICE))
            risk += 25

        known_ips = services.authentication.known_login_ips(user_id)
        if ip and known_ips and ip not in known_ips:
            signals.append(("new IP address", 15, SecurityEvent.Kind.NEW_LOCATION))
            risk += 15

        if ip and ReputationService.is_blocked(ip):
            signals.append(("flagged IP address", 40, SecurityEvent.Kind.SUSPICIOUS_IP))
            risk += 40

        recent_failures = services.authentication.count_failed_attempts(user_id, 60)
        if recent_failures >= 3:
            signals.append((f"{recent_failures} recent failures", 20,
                            SecurityEvent.Kind.BRUTE_FORCE))
            risk += 20

        travel = AnomalyService._check_impossible_travel(user_id, ip)
        if travel:
            signals.append((travel, 50, SecurityEvent.Kind.IMPOSSIBLE_TRAVEL))
            risk += 50

        risk = min(risk, 100)
        if not signals:
            return {"risk_score": 0, "severity": "info", "signals": []}

        if AnomalyService._recently_recorded(signals[0][2], user_id):
            return {"risk_score": risk, "severity": AnomalyService._severity(risk),
                    "signals": [label for label, _, _ in signals], "duplicate": True}

        severity = AnomalyService._severity(risk)
        description = "Sign-in flagged: " + ", ".join(label for label, _, _ in signals)

        event = SecurityEvent.objects.create(
            user_id=user_id, kind=signals[0][2], severity=severity,
            description=description[:400], risk_score=risk,
            ip_address=ip, user_agent=user_agent_string,
            device_fingerprint=device_fingerprint,
            metadata={"signals": [label for label, _, _ in signals]},
        )

        publish(Event.SECURITY_ANOMALY, {
            "event_id": str(event.id),
            "user_id": str(user_id),
            "kind": event.kind,
            "severity": severity,
            "risk_score": risk,
            "ip": ip,
            "device_fingerprint": device_fingerprint,
            "description": description,
        }, actor_id=user_id)

        logger.warning("anomaly user=%s risk=%s signals=%s", user_id, risk,
                       [label for label, _, _ in signals])
        return {"risk_score": risk, "severity": severity,
                "signals": [label for label, _, _ in signals],
                "event_id": str(event.id)}

    @staticmethod
    def _check_impossible_travel(user_id, ip):
        """Compare this login's location with the previous one.

        Uses the member's stated profile location as a proxy when GeoIP is not
        configured — imperfect, but it still catches the obvious cases.
        """
        if not ip:
            return None
        last = CacheService.get("security", "lastloc", user_id)
        here = services.profiles.get_location(user_id)
        if not here:
            return None

        CacheService.set("security", "lastloc", user_id, value={
            "lat": here["latitude"], "lon": here["longitude"],
            "at": timezone.now().timestamp(),
        }, ttl=86400)

        if not last:
            return None

        hours = max((timezone.now().timestamp() - last["at"]) / 3600, 0.01)
        distance = haversine_km(last["lat"], last["lon"], here["latitude"], here["longitude"])
        if distance and distance / hours > IMPOSSIBLE_TRAVEL_KMH:
            return f"{int(distance)} km in {hours:.1f}h"
        return None

    @staticmethod
    def _severity(risk):
        if risk >= 70:
            return AnomalySeverity.CRITICAL
        if risk >= 50:
            return AnomalySeverity.HIGH
        if risk >= 30:
            return AnomalySeverity.MEDIUM
        if risk >= 10:
            return AnomalySeverity.LOW
        return AnomalySeverity.INFO

    #: The same anomaly for the same account is one incident, not many. Without
    #: this an unstable fingerprint (a browser update, a different client) files
    #: a fresh alert on every request and buries the real signals.
    DEDUPE_MINUTES = 60

    @staticmethod
    def _recently_recorded(kind, user_id):
        if not user_id:
            return False
        key = ("dedupe", str(user_id), kind)
        if CacheService.get(*key):
            return True
        CacheService.set(*key, value=1, ttl=AnomalyService.DEDUPE_MINUTES * 60)
        return False

    @staticmethod
    def record(kind, *, user_id=None, severity=AnomalySeverity.LOW,
               description="", request=None, metadata=None):
        """Generic entry point for any module that spots something odd."""
        if AnomalyService._recently_recorded(kind, user_id):
            logger.debug("suppressed duplicate %s for %s", kind, user_id)
            return None

        event = SecurityEvent.objects.create(
            user_id=user_id, kind=kind, severity=severity,
            description=description[:400],
            ip_address=client_ip(request) if request else None,
            user_agent=user_agent(request) if request else "",
            device_fingerprint=(
                request.session.get("device_fingerprint", "") if request else ""
            ),
            path=request.path[:255] if request else "",
            metadata=metadata or {},
        )
        publish(Event.SECURITY_ANOMALY, {
            "event_id": str(event.id), "user_id": str(user_id) if user_id else None,
            "kind": kind, "severity": severity, "description": description,
        }, actor_id=user_id)
        return event

    @staticmethod
    def recent_for(user_id, limit=20):
        return SecurityEvent.objects.filter(user_id=user_id)[:limit]

    @staticmethod
    def open_events(limit=100):
        return SecurityEvent.objects.filter(is_resolved=False).order_by(
            "-severity", "-created_at"
        )[:limit]


class PasswordBreachService:
    """k-anonymity check against Have I Been Pwned.

    Only the first five characters of the SHA-1 hash leave the server, so the
    password itself is never disclosed to the API.
    """

    API = "https://api.pwnedpasswords.com/range/"

    @staticmethod
    def is_breached(password):
        import hashlib as _hashlib
        import urllib.request

        digest = _hashlib.sha1(password.encode()).hexdigest().upper()
        prefix, suffix = digest[:5], digest[5:]

        cached = CacheService.get("security", "hibp", prefix)
        if cached is None:
            try:
                request = urllib.request.Request(
                    f"{PasswordBreachService.API}{prefix}",
                    headers={"User-Agent": "Zynora-Security-Check"},
                )
                with urllib.request.urlopen(request, timeout=3) as response:
                    cached = response.read().decode()
                CacheService.set("security", "hibp", prefix, value=cached, ttl=86400)
            except Exception:  # noqa: BLE001 - availability must not block signup
                logger.info("breach check unavailable; allowing password")
                return False, 0

        for line in cached.splitlines():
            candidate, _, count = line.partition(":")
            if candidate == suffix:
                return True, int(count or 0)
        return False, 0
