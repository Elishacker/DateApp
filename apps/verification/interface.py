"""Public contract of the verification service."""
from apps.common.interface import ModuleInterface

from .models import VerificationBadge, VerificationRequest, VerificationStatus
from .services import VerificationService


class VerificationInterface(ModuleInterface):
    name = "verification"
    depends_on = ("accounts", "authentication", "moderation", "notifications")

    def get_status(self, user_id):
        return VerificationService.status_for(user_id)

    def get_level(self, user_id):
        badge = VerificationBadge.objects.filter(user_id=user_id).first()
        return badge.level if badge else 0

    def is_verified(self, user_id, minimum_level=3):
        return self.get_level(user_id) >= minimum_level

    def has_pending(self, user_id, kind=None):
        qs = VerificationRequest.objects.filter(
            user_id=user_id, status=VerificationStatus.PENDING
        )
        if kind:
            qs = qs.filter(kind=kind)
        return qs.exists()

    def decide(self, request_id, approved, moderator_id=None, reason=""):
        from django.contrib.auth import get_user_model

        request = VerificationService.get(request_id)
        moderator = (
            get_user_model().objects.filter(id=moderator_id).first()
            if moderator_id else None
        )
        if approved:
            VerificationService.approve(request, moderator)
        else:
            VerificationService.reject(request, reason, moderator)
        return {"request_id": str(request.id), "status": request.status}

    def mark_email_verified(self, user_id):
        """Called when authentication confirms an email token."""
        from .models import VerificationKind

        VerificationService._mark_badge(user_id, VerificationKind.EMAIL)
        return True

    def pending_queue(self, limit=100):
        return [
            {
                "request_id": str(r.id),
                "user_id": str(r.user_id),
                "kind": r.kind,
                "challenge_pose": r.challenge_pose,
                "document_url": r.document.url if r.document else "",
                "created_at": r.created_at.isoformat(),
                "attempts": r.attempts,
            }
            for r in VerificationService.pending_queue(limit)
        ]

    def stats(self):
        return {
            "pending": VerificationRequest.objects.filter(
                status=VerificationStatus.PENDING
            ).count(),
            "approved": VerificationRequest.objects.filter(
                status=VerificationStatus.APPROVED
            ).count(),
            "rejected": VerificationRequest.objects.filter(
                status=VerificationStatus.REJECTED
            ).count(),
            "photo_verified_members": VerificationBadge.objects.filter(
                selfie_verified_at__isnull=False
            ).count(),
        }


service = VerificationInterface()
