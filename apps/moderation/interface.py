"""Public contract of the moderation service."""
from apps.common.interface import ModuleInterface

from .models import ModerationCase, TrustScore
from .services import (
    ImageScreeningService,
    ModerationService,
    TextScreeningService,
    TrustService,
)


class ModerationInterface(ModuleInterface):
    name = "moderation"
    depends_on = ()  # screening must never depend on another service being up

    # ---- screening ----------------------------------------------------------
    def screen_text(self, text, owner_id=None):
        """Synchronous verdict used inline by chat and profiles."""
        return TextScreeningService.screen(text, owner_id)

    def queue_image_review(self, *, owner_id, object_type, object_id, url=""):
        case = ImageScreeningService.queue(owner_id, object_type, object_id, url)
        return {"case_id": str(case.id), "status": case.status,
                "risk_score": case.risk_score}

    # ---- trust --------------------------------------------------------------
    def get_trust_score(self, user_id):
        score = TrustService.get(user_id)
        return {
            "score": score.score,
            "band": score.band,
            "is_shadow_banned": score.is_shadow_banned,
            "flags_received": score.flags_received,
            "reports_received": score.reports_received,
        }

    def is_shadow_banned(self, user_id):
        return TrustService.is_shadow_banned(user_id)

    def penalise(self, user_id, points, reason=""):
        return TrustService.penalise(user_id, points, reason)

    def reward(self, user_id, points=2):
        return TrustService.reward(user_id, points)

    def set_shadow_ban(self, user_id, banned=True):
        score = TrustService.set_shadow_ban(user_id, banned)
        return {"is_shadow_banned": score.is_shadow_banned}

    # ---- queue --------------------------------------------------------------
    def queue_stats(self):
        return ModerationService.queue_stats()

    def list_pending(self, object_type=None, limit=100):
        return [
            {
                "case_id": str(c.id),
                "owner_id": str(c.owner_id),
                "object_type": c.object_type,
                "object_id": str(c.object_id),
                "content_url": c.content_url,
                "content_snapshot": c.content_snapshot[:300],
                "risk_score": c.risk_score,
                "severity": c.severity,
                "reasons": c.reasons,
                "created_at": c.created_at.isoformat(),
            }
            for c in ModerationService.pending_cases(object_type, limit)
        ]

    def decide(self, case_id, approved, moderator_id=None, note=""):
        from django.contrib.auth import get_user_model

        case = ModerationService.get(case_id)
        moderator = (
            get_user_model().objects.filter(id=moderator_id).first()
            if moderator_id else None
        )
        ModerationService.decide(case, approved, moderator, note)
        return {"case_id": str(case.id), "status": case.status}

    def flag_content(self, *, owner_id, object_type, object_id, reason="",
                     severity="medium", snapshot=""):
        """Create a case from an external signal (e.g. a user report)."""
        case, _ = ModerationCase.objects.get_or_create(
            object_type=object_type, object_id=object_id,
            defaults={
                "owner_id": owner_id, "severity": severity,
                "reasons": [reason] if reason else [],
                "content_snapshot": snapshot[:2000], "risk_score": 50,
            },
        )
        return {"case_id": str(case.id), "status": case.status}

    def stats(self, since=None):
        qs = ModerationCase.objects.all()
        if since:
            qs = qs.filter(created_at__gte=since)
        return {
            "cases": qs.count(),
            "rejected": qs.filter(status__in=["rejected", "auto_rejected"]).count(),
            "pending": qs.filter(status="pending").count(),
            "shadow_banned": TrustScore.objects.filter(is_shadow_banned=True).count(),
        }


service = ModerationInterface()
