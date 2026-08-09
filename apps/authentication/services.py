"""Authentication business logic."""
import logging

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from apps.common.events import Event, publish
from apps.common.exceptions import PermissionDenied, RateLimited, ValidationError
from apps.common.registry import services
from apps.common.services import CacheService
from apps.common.utils import client_ip, generate_numeric_code, generate_token, hash_token, user_agent

from . import totp
from .models import ActiveSession, LoginAttempt, MFASecret, SecurityToken, SocialAccount, TokenPurpose

logger = logging.getLogger(__name__)
security_log = logging.getLogger("zynora.security")

User = get_user_model()

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


class TokenService:
    """Issues, validates and consumes hashed single-use tokens."""

    TTL_MINUTES = {
        TokenPurpose.EMAIL_VERIFICATION: settings.ZYNORA["EMAIL_TOKEN_TTL_HOURS"] * 60,
        TokenPurpose.PASSWORD_RESET: settings.ZYNORA["PASSWORD_RESET_TTL_MINUTES"],
        TokenPurpose.EMAIL_CHANGE: 60,
        TokenPurpose.PHONE_OTP: settings.ZYNORA["OTP_TTL_MINUTES"],
        TokenPurpose.MFA_CHALLENGE: 10,
        TokenPurpose.DEVICE_CONFIRMATION: 60,
    }

    @staticmethod
    def issue(user, purpose, *, numeric=False, request=None, payload=None):
        """Invalidate outstanding tokens of this purpose, then mint a new one."""
        SecurityToken.objects.filter(
            user=user, purpose=purpose, used_at__isnull=True
        ).update(used_at=timezone.now())

        raw = generate_numeric_code(6) if numeric else generate_token(48)
        token = SecurityToken.objects.create(
            user=user,
            purpose=purpose,
            token_hash=hash_token(raw),
            expires_at=timezone.now() + timezone.timedelta(
                minutes=TokenService.TTL_MINUTES.get(purpose, 30)
            ),
            ip_address=client_ip(request) if request else None,
            user_agent=user_agent(request) if request else "",
            payload=payload or {},
        )
        return raw, token

    @staticmethod
    def validate(raw, purpose):
        token = SecurityToken.objects.filter(
            purpose=purpose, token_hash=hash_token(raw), used_at__isnull=True
        ).select_related("user").first()

        if not token:
            raise ValidationError("That link is invalid or has already been used.")
        if token.is_expired:
            raise ValidationError("That link has expired. Request a new one.")
        return token

    @staticmethod
    @transaction.atomic
    def consume(raw, purpose):
        token = TokenService.validate(raw, purpose)
        token.consume()
        return token


class RegistrationService:
    """Signup orchestration: create the identity, then start verification."""

    @staticmethod
    @transaction.atomic
    def register(*, email, username, password, first_name="", date_of_birth=None,
                 phone=None, accepted_terms=False, marketing_opt_in=False, request=None):
        # Identity creation belongs to accounts; we go through its contract and
        # then load the shared User model (identity is the one shared kernel).
        created = services.accounts.create_account(
            email=email, username=username, password=password,
            first_name=first_name, date_of_birth=date_of_birth, phone=phone,
            accepted_terms=accepted_terms, marketing_opt_in=marketing_opt_in,
        )
        user = User.objects.get(id=created["id"])

        raw_token, _ = TokenService.issue(user, TokenPurpose.EMAIL_VERIFICATION, request=request)
        EmailDeliveryService.send_verification(user, raw_token)

        if request:
            fingerprint = request.session.get("device_fingerprint", "")
            if fingerprint:
                services.accounts.register_device(
                    user.id, fingerprint, user_agent(request), client_ip(request)
                )
        return user, raw_token

    @staticmethod
    def resend_verification(user, request=None):
        if user.is_email_verified:
            raise ValidationError("This email address is already verified.")

        throttle_key = ("resend_verification", str(user.id))
        if CacheService.get(*throttle_key):
            raise RateLimited("Please wait a minute before requesting another email.")
        CacheService.set(*throttle_key, value=1, ttl=60)

        raw_token, _ = TokenService.issue(user, TokenPurpose.EMAIL_VERIFICATION, request=request)
        EmailDeliveryService.send_verification(user, raw_token)
        return raw_token

    @staticmethod
    def verify_email(raw_token):
        token = TokenService.consume(raw_token, TokenPurpose.EMAIL_VERIFICATION)
        publish(Event.EMAIL_VERIFIED, {"user_id": str(token.user_id)}, actor_id=token.user_id)
        return token.user


class LoginService:
    """Credential checking, lockout, MFA gating and session issuance."""

    @staticmethod
    def _record(identifier, outcome, request=None, user=None, detail="", risk=0):
        return LoginAttempt.objects.create(
            user=user,
            identifier=identifier[:255],
            outcome=outcome,
            ip_address=client_ip(request) if request else None,
            user_agent=user_agent(request) if request else "",
            device_fingerprint=(request.session.get("device_fingerprint", "") if request else ""),
            risk_score=risk,
            detail=detail[:255],
        )

    @staticmethod
    def _throttle(identifier, request):
        limit, window = settings.ZYNORA["LOGIN_RATE_LIMIT"]
        ip = client_ip(request) if request else "unknown"
        for scope in (f"id:{identifier}", f"ip:{ip}"):
            if CacheService.incr("login", scope, ttl=window) > limit:
                security_log.warning("login throttled scope=%s", scope)
                raise RateLimited("Too many sign-in attempts. Try again in a few minutes.")

    @staticmethod
    def authenticate(identifier, password, request=None):
        """Return ``(user, requires_mfa)`` or raise a domain error."""
        identifier = (identifier or "").strip()
        LoginService._throttle(identifier, request)

        user = authenticate(request, username=identifier, password=password)

        if user is None:
            candidate = User.objects.filter(email__iexact=identifier).first() \
                or User.objects.filter(username__iexact=identifier).first() \
                or User.objects.filter(phone=identifier).first()

            if candidate is None:
                LoginService._record(identifier, LoginAttempt.Outcome.UNKNOWN_USER, request)
                raise ValidationError("Incorrect email or password.")

            if candidate.is_banned:
                LoginService._record(identifier, LoginAttempt.Outcome.BANNED, request, candidate)
                raise PermissionDenied("This account has been suspended. Contact support.")

            if candidate.is_locked:
                LoginService._record(identifier, LoginAttempt.Outcome.LOCKED, request, candidate)
                raise PermissionDenied(
                    "Too many failed attempts. This account is temporarily locked."
                )

            LoginService._register_failure(candidate)
            LoginService._record(identifier, LoginAttempt.Outcome.BAD_CREDENTIALS, request, candidate)
            raise ValidationError("Incorrect email or password.")

        user.failed_login_attempts = 0
        user.locked_until = None
        user.save(update_fields=["failed_login_attempts", "locked_until"])

        if user.is_mfa_enabled:
            LoginService._record(identifier, LoginAttempt.Outcome.MFA_REQUIRED, request, user)
            return user, True

        return user, False

    @staticmethod
    def _register_failure(user):
        user.failed_login_attempts += 1
        fields = ["failed_login_attempts"]
        if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
            user.locked_until = timezone.now() + timezone.timedelta(minutes=LOCKOUT_MINUTES)
            fields.append("locked_until")
            security_log.warning("account locked user=%s", user.id)
        user.save(update_fields=fields)

    @staticmethod
    def complete_login(user, request=None, mfa_used=False):
        """Runs after every successful authentication, session or API."""
        LoginService._record(
            user.email, LoginAttempt.Outcome.SUCCESS, request, user,
            detail="mfa" if mfa_used else "",
        )

        ip = client_ip(request) if request else None
        fingerprint = request.session.get("device_fingerprint", "") if request else ""

        user.touch_activity(ip)
        user.mark_online(True)

        device = None
        if fingerprint:
            device = services.accounts.register_device(
                user.id, fingerprint, user_agent(request) if request else "", ip
            )

        ActiveSession.objects.create(
            user=user,
            session_key=request.session.session_key if request and request.session.session_key else "",
            device_fingerprint=fingerprint,
            ip_address=ip,
            user_agent=user_agent(request) if request else "",
            expires_at=timezone.now() + timezone.timedelta(seconds=settings.SESSION_COOKIE_AGE),
        )

        publish(Event.LOGIN_SUCCEEDED, {
            "user_id": str(user.id),
            "ip": ip,
            "device_fingerprint": fingerprint,
            "device_is_new": bool(device and not device.get("is_trusted")),
            "mfa_used": mfa_used,
        }, actor_id=user.id)
        return user

    @staticmethod
    def logout(user, request=None):
        if request and request.session.session_key:
            ActiveSession.objects.filter(
                user=user, session_key=request.session.session_key
            ).update(revoked_at=timezone.now())
        user.mark_online(False)
        publish(Event.LOGOUT, {"user_id": str(user.id)}, actor_id=user.id)

    @staticmethod
    def issue_jwt(user):
        refresh = RefreshToken.for_user(user)
        return {"access": str(refresh.access_token), "refresh": str(refresh)}


class MFAService:
    """TOTP enrolment, verification and recovery codes."""

    @staticmethod
    def begin_enrolment(user):
        secret = totp.generate_secret()
        MFASecret.objects.update_or_create(
            user=user,
            defaults={"secret": secret, "is_confirmed": False,
                      "recovery_codes": [], "last_used_counter": 0},
        )
        return {
            "secret": secret,
            "otpauth_url": totp.provisioning_uri(secret, user.email),
        }

    @staticmethod
    @transaction.atomic
    def confirm_enrolment(user, code):
        try:
            mfa = MFASecret.objects.select_for_update().get(user=user)
        except MFASecret.DoesNotExist as exc:
            raise ValidationError("Start two-factor setup first.") from exc

        counter = totp.verify_code(mfa.secret, code, last_counter=mfa.last_used_counter)
        if counter is None:
            raise ValidationError("That code is not valid. Check your authenticator app.")

        codes = totp.generate_recovery_codes()
        mfa.is_confirmed = True
        mfa.confirmed_at = timezone.now()
        mfa.last_used_counter = counter
        mfa.recovery_codes = [{"hash": hash_token(c), "used": False} for c in codes]
        mfa.save()

        user.is_mfa_enabled = True
        user.save(update_fields=["is_mfa_enabled"])

        publish(Event.MFA_ENABLED, {"user_id": str(user.id)}, actor_id=user.id)
        return codes  # shown exactly once

    @staticmethod
    @transaction.atomic
    def verify(user, code):
        """Accept either a TOTP code or an unused recovery code."""
        try:
            mfa = MFASecret.objects.select_for_update().get(user=user, is_confirmed=True)
        except MFASecret.DoesNotExist as exc:
            raise ValidationError("Two-factor authentication is not enabled.") from exc

        counter = totp.verify_code(mfa.secret, code, last_counter=mfa.last_used_counter)
        if counter is not None:
            mfa.last_used_counter = counter
            mfa.save(update_fields=["last_used_counter"])
            return True

        digest = hash_token((code or "").strip().lower())
        for entry in mfa.recovery_codes:
            if entry["hash"] == digest and not entry["used"]:
                entry["used"] = True
                mfa.save(update_fields=["recovery_codes"])
                security_log.info("recovery code used user=%s", user.id)
                return True

        raise ValidationError("That code is not valid.")

    @staticmethod
    def disable(user, password):
        if not user.check_password(password):
            raise ValidationError("Incorrect password.")
        MFASecret.objects.filter(user=user).delete()
        user.is_mfa_enabled = False
        user.save(update_fields=["is_mfa_enabled"])
        publish(Event.MFA_DISABLED, {"user_id": str(user.id)}, actor_id=user.id)

    @staticmethod
    def regenerate_recovery_codes(user):
        mfa = MFASecret.objects.filter(user=user, is_confirmed=True).first()
        if not mfa:
            raise ValidationError("Two-factor authentication is not enabled.")
        codes = totp.generate_recovery_codes()
        mfa.recovery_codes = [{"hash": hash_token(c), "used": False} for c in codes]
        mfa.save(update_fields=["recovery_codes"])
        return codes


class PasswordService:
    @staticmethod
    def request_reset(email, request=None):
        """Always reports success — never confirms whether an account exists."""
        user = User.objects.filter(email__iexact=(email or "").strip()).first()
        if user:
            raw, _ = TokenService.issue(user, TokenPurpose.PASSWORD_RESET, request=request)
            EmailDeliveryService.send_password_reset(user, raw)
            publish(Event.PASSWORD_RESET_REQUESTED, {"user_id": str(user.id)}, actor_id=user.id)
        else:
            security_log.info("password reset requested for unknown address")
        return True

    @staticmethod
    @transaction.atomic
    def reset(raw_token, new_password):
        from django.contrib.auth.password_validation import validate_password

        token = TokenService.validate(raw_token, TokenPurpose.PASSWORD_RESET)
        user = token.user
        validate_password(new_password, user)

        user.set_password(new_password)
        user.password_changed_at = timezone.now()
        user.must_change_password = False
        user.failed_login_attempts = 0
        user.locked_until = None
        user.save()
        token.consume()

        # A reset invalidates every existing session everywhere.
        ActiveSession.objects.filter(user=user, revoked_at__isnull=True).update(
            revoked_at=timezone.now()
        )
        publish(Event.PASSWORD_CHANGED, {"user_id": str(user.id), "via": "reset"}, actor_id=user.id)
        return user

    @staticmethod
    def change(user, current_password, new_password):
        from django.contrib.auth.password_validation import validate_password

        if not user.check_password(current_password):
            raise ValidationError("Your current password is incorrect.")
        if current_password == new_password:
            raise ValidationError("Choose a password you have not used before.")
        validate_password(new_password, user)

        user.set_password(new_password)
        user.password_changed_at = timezone.now()
        user.must_change_password = False
        user.save()
        publish(Event.PASSWORD_CHANGED, {"user_id": str(user.id), "via": "settings"}, actor_id=user.id)
        return user


class SocialAuthService:
    """Provider-agnostic link/lookup. Token exchange belongs in the adapter."""

    @staticmethod
    @transaction.atomic
    def connect_or_create(*, provider, uid, email, first_name="", extra=None):
        link = SocialAccount.objects.filter(provider=provider, provider_uid=uid).first()
        if link:
            return link.user, False

        user = User.objects.filter(email__iexact=email).first()
        created = False
        if not user:
            base = (email or "").split("@")[0][:20] or "member"
            username = base
            suffix = 1
            while User.objects.filter(username=username).exists():
                suffix += 1
                username = f"{base}{suffix}"[:30]

            record = services.accounts.create_account(
                email=email, username=username, password=generate_token(32),
                first_name=first_name, accepted_terms=True,
            )
            user = User.objects.get(id=record["id"])
            # The provider already proved control of the address.
            user.is_email_verified = True
            user.status = "active"
            user.save(update_fields=["is_email_verified", "status"])
            created = True

        SocialAccount.objects.create(
            provider=provider, provider_uid=uid, user=user,
            email=email or "", extra_data=extra or {},
        )
        return user, created


class EmailDeliveryService:
    """Thin wrapper so callers never touch Django's mail API directly.

    Delivery is queued through the notifications service when it is available,
    which keeps SMTP latency out of the request path.
    """

    @staticmethod
    def _send(user, template, subject, context):
        try:
            services.notifications.send_transactional_email(
                user_id=str(user.id), template=template, subject=subject, context=context
            )
        except Exception:  # noqa: BLE001 - never block signup on mail failure
            logger.exception("Failed to queue %s email for %s", template, user.id)

    @staticmethod
    def send_verification(user, raw_token):
        EmailDeliveryService._send(
            user, "verify_email", "Confirm your Zynora email address",
            {"token": raw_token, "name": user.display_name},
        )

    @staticmethod
    def send_password_reset(user, raw_token):
        EmailDeliveryService._send(
            user, "password_reset", "Reset your Zynora password",
            {"token": raw_token, "name": user.display_name,
             "ttl_minutes": settings.ZYNORA["PASSWORD_RESET_TTL_MINUTES"]},
        )
