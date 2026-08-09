"""Public contract of the authentication service."""
from django.utils import timezone

from apps.common.interface import ModuleInterface

from .models import ActiveSession, LoginAttempt, MFASecret, SocialAccount
from .services import LoginService, MFAService, TokenService


class AuthenticationInterface(ModuleInterface):
    name = "authentication"
    depends_on = ("accounts", "notifications")

    # ---- session / token facts ---------------------------------------------
    def issue_jwt(self, user_id):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.filter(id=user_id).first()
        return LoginService.issue_jwt(user) if user else None

    def list_active_sessions(self, user_id):
        rows = ActiveSession.objects.filter(user_id=user_id, revoked_at__isnull=True)
        return [
            {
                "id": str(r.id),
                "ip_address": r.ip_address,
                "user_agent": r.user_agent,
                "device_fingerprint": r.device_fingerprint,
                "last_seen_at": r.last_seen_at.isoformat(),
                "is_active": r.is_active,
            }
            for r in rows
        ]

    def revoke_all_sessions(self, user_id, except_session_key=None):
        qs = ActiveSession.objects.filter(user_id=user_id, revoked_at__isnull=True)
        if except_session_key:
            qs = qs.exclude(session_key=except_session_key)
        return qs.update(revoked_at=timezone.now())

    # ---- login telemetry (consumed by security & analytics) -----------------
    def recent_login_attempts(self, user_id, limit=20):
        rows = LoginAttempt.objects.filter(user_id=user_id)[:limit]
        return [
            {
                "id": str(r.id),
                "outcome": r.outcome,
                "ip_address": r.ip_address,
                "user_agent": r.user_agent,
                "device_fingerprint": r.device_fingerprint,
                "risk_score": r.risk_score,
                "created_at": r.created_at.isoformat(),
                "was_successful": r.was_successful,
            }
            for r in rows
        ]

    def count_failed_attempts(self, user_id, since_minutes=60):
        cutoff = timezone.now() - timezone.timedelta(minutes=since_minutes)
        return LoginAttempt.objects.filter(
            user_id=user_id, created_at__gte=cutoff
        ).exclude(outcome=LoginAttempt.Outcome.SUCCESS).count()

    def known_login_ips(self, user_id, limit=50):
        return list(
            LoginAttempt.objects.filter(
                user_id=user_id, outcome=LoginAttempt.Outcome.SUCCESS
            ).values_list("ip_address", flat=True).distinct()[:limit]
        )

    def failed_attempts_by_ip(self, threshold=20, window_minutes=15):
        """IPs failing against many distinct accounts — a stuffing signature.

        Exposed here so the security service can detect the pattern without
        reading the login ledger's tables.
        """
        from django.db.models import Count

        since = timezone.now() - timezone.timedelta(minutes=window_minutes)
        rows = (
            LoginAttempt.objects.filter(created_at__gte=since)
            .exclude(outcome=LoginAttempt.Outcome.SUCCESS)
            .exclude(ip_address__isnull=True)
            .values("ip_address")
            .annotate(accounts=Count("identifier", distinct=True))
            .filter(accounts__gte=threshold)
        )
        return [{"ip": r["ip_address"], "accounts": r["accounts"]} for r in rows]

    def annotate_risk(self, attempt_id, risk_score):
        """Lets the security service write back its anomaly verdict."""
        return LoginAttempt.objects.filter(id=attempt_id).update(risk_score=risk_score)

    # ---- MFA / social state -------------------------------------------------
    def mfa_status(self, user_id):
        mfa = MFASecret.objects.filter(user_id=user_id).first()
        if not mfa:
            return {"enabled": False, "confirmed": False, "recovery_codes_remaining": 0}
        return {
            "enabled": True,
            "confirmed": mfa.is_confirmed,
            "confirmed_at": mfa.confirmed_at.isoformat() if mfa.confirmed_at else None,
            "recovery_codes_remaining": mfa.recovery_codes_remaining,
        }

    def verify_mfa_code(self, user_id, code):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.filter(id=user_id).first()
        if not user:
            return False
        try:
            return MFAService.verify(user, code)
        except Exception:  # noqa: BLE001 - contract returns a boolean
            return False

    def linked_providers(self, user_id):
        return list(
            SocialAccount.objects.filter(user_id=user_id).values_list("provider", flat=True)
        )

    # ---- tokens used by other flows (e.g. verification service) -------------
    def issue_otp(self, user_id, purpose="phone_otp"):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.filter(id=user_id).first()
        if not user:
            return None
        raw, token = TokenService.issue(user, purpose, numeric=True)
        return {"code": raw, "expires_at": token.expires_at.isoformat()}

    def consume_otp(self, raw_code, purpose="phone_otp"):
        token = TokenService.consume(raw_code, purpose)
        return {"user_id": str(token.user_id), "payload": token.payload}


service = AuthenticationInterface()
