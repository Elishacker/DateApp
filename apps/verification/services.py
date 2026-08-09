"""Verification workflow."""
import logging
import secrets

from django.db import transaction
from django.utils import timezone

from apps.common.events import Event, publish
from apps.common.exceptions import NotFound, RateLimited, ValidationError
from apps.common.registry import services

from .models import (
    VerificationBadge,
    VerificationKind,
    VerificationRequest,
    VerificationStatus,
)

logger = logging.getLogger(__name__)

#: Poses a member may be asked to reproduce for photo verification.
CHALLENGE_POSES = (
    "Hold up two fingers next to your face",
    "Place your right hand on your left shoulder",
    "Give a thumbs up beside your chin",
    "Touch your left ear with your right hand",
    "Make a peace sign below your chin",
    "Point at the camera with one finger",
)

MAX_ATTEMPTS_PER_DAY = 3


class VerificationService:
    @staticmethod
    def badge(user_id):
        badge, _ = VerificationBadge.objects.get_or_create(user_id=user_id)
        return badge

    @staticmethod
    def status_for(user_id):
        """Render-ready verification panel."""
        badge = VerificationService.badge(user_id)
        pending = set(
            VerificationRequest.objects.filter(
                user_id=user_id, status=VerificationStatus.PENDING
            ).values_list("kind", flat=True)
        )

        steps = []
        for kind, label, done_at, blurb in (
            (VerificationKind.EMAIL, "Email address", badge.email_verified_at,
             "Confirms you can be contacted."),
            (VerificationKind.PHONE, "Phone number", badge.phone_verified_at,
             "Adds a second way to secure your account."),
            (VerificationKind.SELFIE, "Photo verification", badge.selfie_verified_at,
             "Earns the blue tick and far more matches."),
            (VerificationKind.GOVERNMENT_ID, "Government ID", badge.identity_verified_at,
             "Highest level of trust on Zynora."),
        ):
            steps.append({
                "kind": kind,
                "label": label,
                "blurb": blurb,
                "is_done": bool(done_at),
                "is_pending": kind in pending,
                "completed_at": done_at.isoformat() if done_at else None,
            })

        return {
            "level": badge.level,
            "label": badge.label,
            "percent": int(badge.level / 4 * 100),
            "steps": steps,
            "next_step": next((s for s in steps if not s["is_done"]), None),
        }

    @staticmethod
    def new_challenge():
        return secrets.choice(CHALLENGE_POSES)

    @staticmethod
    def _guard_attempts(user_id, kind):
        since = timezone.now() - timezone.timedelta(days=1)
        attempts = VerificationRequest.objects.filter(
            user_id=user_id, kind=kind, created_at__gte=since
        ).count()
        if attempts >= MAX_ATTEMPTS_PER_DAY:
            raise RateLimited(
                f"You've made {attempts} attempts today. Try again tomorrow."
            )

    # ---- submission ---------------------------------------------------------
    @staticmethod
    @transaction.atomic
    def submit_photo(user, document, challenge_pose="", kind=VerificationKind.SELFIE):
        VerificationService._guard_attempts(user.id, kind)

        if VerificationRequest.objects.filter(
            user=user, kind=kind, status=VerificationStatus.PENDING
        ).exists():
            raise ValidationError("You already have a verification under review.")

        request = VerificationRequest.objects.create(
            user=user, kind=kind, document=document,
            challenge_pose=challenge_pose or VerificationService.new_challenge(),
            expires_at=timezone.now() + timezone.timedelta(days=7),
        )

        # Route through moderation so verification photos join one review queue.
        services.moderation.queue_image_review(
            owner_id=str(user.id), object_type="verification_photo",
            object_id=str(request.id), url="",
        )

        publish(Event.VERIFICATION_SUBMITTED, {
            "request_id": str(request.id), "user_id": str(user.id), "kind": kind,
        }, actor_id=user.id)
        return request

    @staticmethod
    def start_phone_verification(user, phone):
        VerificationService._guard_attempts(user.id, VerificationKind.PHONE)

        request = VerificationRequest.objects.create(
            user=user, kind=VerificationKind.PHONE, target_value=phone,
            expires_at=timezone.now() + timezone.timedelta(minutes=10),
        )
        otp = services.authentication.issue_otp(str(user.id), "phone_otp")
        if not otp:
            raise ValidationError("Could not send a code right now.")

        services.notifications.notify(
            str(user.id), "verification",
            title="Your Zynora verification code",
            body=f"Your code is {otp['code']}. It expires in 10 minutes.",
            channels=["sms"],
        )
        return {"request_id": str(request.id), "expires_at": otp["expires_at"]}

    @staticmethod
    @transaction.atomic
    def confirm_phone(user, code):
        try:
            result = services.authentication.consume_otp(code, "phone_otp")
        except Exception as exc:  # noqa: BLE001
            raise ValidationError("That code is not valid or has expired.") from exc

        if str(result.get("user_id")) != str(user.id):
            raise ValidationError("That code is not valid.")

        request = VerificationRequest.objects.filter(
            user=user, kind=VerificationKind.PHONE, status=VerificationStatus.PENDING
        ).order_by("-created_at").first()
        if request:
            VerificationService.approve(request)
        else:
            VerificationService._mark_badge(user.id, VerificationKind.PHONE)
            publish(Event.VERIFICATION_APPROVED, {
                "user_id": str(user.id), "kind": VerificationKind.PHONE,
            }, actor_id=user.id)
        return True

    # ---- decisions ----------------------------------------------------------
    @staticmethod
    @transaction.atomic
    def approve(request, moderator=None, confidence=None):
        request.approve(moderator, confidence)
        VerificationService._mark_badge(request.user_id, request.kind)

        publish(Event.VERIFICATION_APPROVED, {
            "request_id": str(request.id),
            "user_id": str(request.user_id),
            "kind": request.kind,
        }, actor_id=getattr(moderator, "id", None) or request.user_id)

        services.moderation.reward(str(request.user_id), points=10)
        logger.info("verification %s approved for %s", request.kind, request.user_id)
        return request

    @staticmethod
    def reject(request, reason="", moderator=None):
        request.reject(reason, moderator)
        publish(Event.VERIFICATION_REJECTED, {
            "request_id": str(request.id),
            "user_id": str(request.user_id),
            "kind": request.kind,
            "reason": reason,
        }, actor_id=getattr(moderator, "id", None))
        return request

    @staticmethod
    def _mark_badge(user_id, kind):
        badge = VerificationService.badge(user_id)
        field = {
            VerificationKind.EMAIL: "email_verified_at",
            VerificationKind.PHONE: "phone_verified_at",
            VerificationKind.SELFIE: "selfie_verified_at",
            VerificationKind.GOVERNMENT_ID: "identity_verified_at",
        }[kind]
        setattr(badge, field, timezone.now())
        badge.save(update_fields=[field, "updated_at"])
        return badge

    @staticmethod
    def pending_queue(limit=100):
        return VerificationRequest.objects.filter(
            status=VerificationStatus.PENDING
        ).order_by("created_at")[:limit]

    @staticmethod
    def get(request_id):
        request = VerificationRequest.objects.filter(id=request_id).first()
        if not request:
            raise NotFound("Verification request not found.")
        return request
