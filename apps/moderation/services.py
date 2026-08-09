"""Automated screening and moderator workflow."""
import logging
import re

from django.utils import timezone

from apps.common.events import Event, publish
from apps.common.exceptions import NotFound
from apps.common.services import CacheService

from .models import BannedTerm, ModerationCase, Severity, TrustScore

logger = logging.getLogger(__name__)

#: Patterns that indicate off-platform contact solicitation or scam behaviour.
#: Naming another messaging app is weighted HIGH rather than MEDIUM: moving a
#: conversation off Zynora is the first step in almost every romance scam, and
#: it removes the member from every safety control this platform provides.
RISK_PATTERNS = (
    (r"\b(?:\+?\d[\d\s\-()]{7,})\b", "phone number shared", Severity.LOW),
    (r"\b[\w.+-]+@[\w-]+\.[\w.]+\b", "email address shared", Severity.LOW),
    (r"\b(?:whatsapp|telegram|snapchat|instagram|ig)\b[\s:@]*\w*", "off-platform contact", Severity.HIGH),
    (r"\b(?:bitcoin|btc|usdt|crypto|forex|investment opportunity)\b", "financial solicitation", Severity.HIGH),
    (r"\b(?:send|transfer|wire)\s+(?:me\s+)?(?:money|cash|funds)\b", "money request", Severity.CRITICAL),
    (r"\b(?:onlyfans|cashapp|paypal\.me)\b", "monetisation link", Severity.HIGH),
    (r"https?://\S+", "external link", Severity.LOW),
)

SEVERITY_WEIGHT = {
    Severity.LOW: 10,
    Severity.MEDIUM: 25,
    Severity.HIGH: 45,
    Severity.CRITICAL: 80,
}

TERM_CACHE_SECONDS = 600


class TextScreeningService:
    """Fast, deterministic first pass. An ML model can slot in behind this API."""

    @staticmethod
    def _terms():
        cached = CacheService.get("moderation", "terms")
        if cached is not None:
            return cached
        terms = [
            {"term": t.term, "action": t.action, "severity": t.severity,
             "is_regex": t.is_regex, "id": str(t.id)}
            for t in BannedTerm.objects.filter(is_active=True)
        ]
        CacheService.set("moderation", "terms", value=terms, ttl=TERM_CACHE_SECONDS)
        return terms

    @staticmethod
    def screen(text, owner_id=None):
        """Return a verdict dict: blocked / flagged / clean_text / reasons."""
        if not text or not text.strip():
            return {"blocked": False, "flagged": False, "clean_text": text,
                    "reasons": [], "risk_score": 0}

        reasons = []
        risk = 0
        clean = text
        blocked = False

        for entry in TextScreeningService._terms():
            pattern = entry["term"] if entry["is_regex"] else re.escape(entry["term"])
            if not re.search(pattern, text, re.IGNORECASE):
                continue

            reasons.append(f"banned term: {entry['term']}")
            risk += SEVERITY_WEIGHT.get(entry["severity"], 20)

            if entry["action"] == BannedTerm.Action.BLOCK:
                blocked = True
            elif entry["action"] == BannedTerm.Action.MASK:
                clean = re.sub(pattern, "***", clean, flags=re.IGNORECASE)

            BannedTerm.objects.filter(id=entry["id"]).update(
                hit_count=models_increment("hit_count")
            )

        for pattern, label, severity in RISK_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                reasons.append(label)
                risk += SEVERITY_WEIGHT.get(severity, 20)
                if severity == Severity.CRITICAL:
                    blocked = True

        risk = min(risk, 100)
        flagged = risk >= 40 or blocked

        if flagged and owner_id:
            TrustService.penalise(owner_id, 5 if not blocked else 15,
                                  reason="; ".join(reasons[:3]))

        return {
            "blocked": blocked,
            "flagged": flagged,
            "clean_text": clean,
            "reasons": reasons,
            "risk_score": risk,
            "message": TextScreeningService._message(reasons) if blocked else "",
        }

    @staticmethod
    def _message(reasons):
        if any("money" in r or "financial" in r for r in reasons):
            return ("That message looks like a financial solicitation, which we don't "
                    "allow. If someone asks you for money, please report them.")
        return "That message was blocked by our safety filters."


class ImageScreeningService:
    """Queue images for review.

    The heuristic pass here is intentionally conservative; wire a real
    classifier (AWS Rekognition, Google Vision, an in-house model) into
    ``analyse`` and the rest of the platform is unchanged.
    """

    @staticmethod
    def queue(owner_id, object_type, object_id, url=""):
        case, created = ModerationCase.objects.get_or_create(
            object_type=object_type, object_id=object_id,
            defaults={"owner_id": owner_id, "content_url": url},
        )
        if not created:
            return case

        verdict = ImageScreeningService.analyse(url, owner_id)
        case.risk_score = verdict["risk_score"]
        case.reasons = verdict["reasons"]
        case.severity = verdict["severity"]
        case.save(update_fields=["risk_score", "reasons", "severity"])

        if verdict["auto_decidable"]:
            ModerationService.decide(case, approved=verdict["approved"],
                                     note="Automated review")
        return case

    @staticmethod
    def analyse(url, owner_id=None):
        """Trust-weighted auto-approval.

        A trusted member's upload clears immediately; a watched member's upload
        always reaches a human. That keeps the queue small without lowering the
        bar where it matters.
        """
        trust = TrustService.get(owner_id) if owner_id else None
        band = trust.band if trust else "normal"

        if band == "trusted":
            return {"auto_decidable": True, "approved": True, "risk_score": 0,
                    "reasons": ["trusted uploader"], "severity": Severity.LOW}
        if band == "high_risk":
            return {"auto_decidable": False, "approved": False, "risk_score": 70,
                    "reasons": ["low trust score"], "severity": Severity.HIGH}
        return {"auto_decidable": True, "approved": True, "risk_score": 10,
                "reasons": [], "severity": Severity.LOW}


class ModerationService:
    @staticmethod
    def pending_cases(object_type=None, limit=100):
        qs = ModerationCase.objects.filter(status=ModerationCase.Status.PENDING)
        if object_type:
            qs = qs.filter(object_type=object_type)
        return qs.order_by("-risk_score", "created_at")[:limit]

    @staticmethod
    def get(case_id):
        case = ModerationCase.objects.filter(id=case_id).first()
        if not case:
            raise NotFound("Moderation case not found.")
        return case

    @staticmethod
    def decide(case, approved, moderator=None, note=""):
        """Record the verdict and let the owning module apply it."""
        case.resolve(approved, moderator, note)

        if not approved:
            TrustService.penalise(case.owner_id, 10, reason=f"{case.object_type} rejected")
            TrustScore.objects.filter(user_id=case.owner_id).update(
                content_rejected=models_increment("content_rejected")
            )

        publish(Event.CONTENT_FLAGGED, {
            "case_id": str(case.id),
            "owner_id": str(case.owner_id),
            "object_type": case.object_type,
            "object_id": str(case.object_id),
            "approved": approved,
            "reason": note or "; ".join(case.reasons),
            "severity": case.severity,
        }, actor_id=getattr(moderator, "id", None))
        return case

    @staticmethod
    def queue_stats():
        qs = ModerationCase.objects.filter(status=ModerationCase.Status.PENDING)
        return {
            "pending": qs.count(),
            "photos": qs.filter(object_type=ModerationCase.ObjectType.PROFILE_PHOTO).count(),
            "messages": qs.filter(object_type=ModerationCase.ObjectType.MESSAGE).count(),
            "high_risk": qs.filter(risk_score__gte=60).count(),
        }


class TrustService:
    @staticmethod
    def get(user_id):
        score, _ = TrustScore.objects.get_or_create(user_id=user_id)
        return score

    @staticmethod
    def penalise(user_id, points, reason=""):
        if not user_id:
            return None
        return TrustService.get(user_id).penalise(points, reason)

    @staticmethod
    def reward(user_id, points=2):
        score = TrustService.get(user_id)
        score.score = min(score.score + points, 100)
        score.save(update_fields=["score", "updated_at"])
        return score.score

    @staticmethod
    def is_shadow_banned(user_id):
        return TrustScore.objects.filter(user_id=user_id, is_shadow_banned=True).exists()

    @staticmethod
    def set_shadow_ban(user_id, banned=True):
        score = TrustService.get(user_id)
        score.is_shadow_banned = banned
        score.shadow_banned_at = timezone.now() if banned else None
        score.save(update_fields=["is_shadow_banned", "shadow_banned_at"])
        return score


def models_increment(field):
    """``F(field) + 1`` without importing F at every call site."""
    from django.db.models import F

    return F(field) + 1
