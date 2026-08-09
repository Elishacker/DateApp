"""Swipe business logic: quotas, intent recording, rewind."""
import logging

from django.db import transaction
from django.utils import timezone

from apps.common.events import Event, publish
from apps.common.exceptions import NotFound, QuotaExceeded, ValidationError
from apps.common.registry import services

from .models import Like, LikeType, SwipeQuota

logger = logging.getLogger(__name__)


class QuotaService:
    """Counts swipes; subscriptions supplies the ceiling."""

    @staticmethod
    def get(user):
        quota, _ = SwipeQuota.objects.get_or_create(user=user)
        # Lazy daily reset — cheaper and more reliable than depending on beat.
        if quota.reset_at.date() < timezone.now().date():
            quota.reset()
        return quota

    @staticmethod
    def limits(user_id):
        return services.subscriptions.get_quota_limits(str(user_id))

    @staticmethod
    def snapshot(user):
        quota = QuotaService.get(user)
        limits = QuotaService.limits(user.id)
        return {
            "likes_used": quota.likes_used,
            "likes_limit": limits["daily_likes"],
            "likes_remaining": _remaining(limits["daily_likes"], quota.likes_used),
            "super_likes_used": quota.super_likes_used,
            "super_likes_limit": limits["daily_super_likes"],
            "super_likes_remaining": _remaining(limits["daily_super_likes"], quota.super_likes_used),
            "rewinds_used": quota.rewinds_used,
            "rewinds_limit": limits["daily_rewinds"],
            "rewinds_remaining": _remaining(limits["daily_rewinds"], quota.rewinds_used),
            "is_unlimited": limits["daily_likes"] is None,
        }

    @staticmethod
    def consume(user, field, limit_key):
        quota = QuotaService.get(user)
        limit = QuotaService.limits(user.id)[limit_key]
        used = getattr(quota, field)
        if limit is not None and used >= limit:
            raise QuotaExceeded(
                f"You've used all {limit} of today's {field.replace('_', ' ').replace(' used', '')}. "
                "Upgrade for more.",
                limit=limit, used=used,
            )
        setattr(quota, field, used + 1)
        quota.save(update_fields=[field, "updated_at"])
        return quota


class LikeService:
    @staticmethod
    @transaction.atomic
    def swipe(sender, receiver_id, kind=LikeType.LIKE, message="", source="discovery"):
        """Record a swipe and return a render-ready result dict."""
        receiver_id = str(receiver_id)
        if str(sender.id) == receiver_id:
            raise ValidationError("You cannot swipe on yourself.")
        if not services.accounts.is_active_member(receiver_id):
            raise NotFound("That member is no longer available.")
        if services.reports.is_blocked_between(str(sender.id), receiver_id):
            raise ValidationError("That member is not available.")

        existing = Like.objects.filter(sender=sender, receiver_id=receiver_id).first()
        if existing and not existing.is_rewound:
            # Repeating the same intent is a no-op rather than an error: liked
            # profiles stay in the feed, so a second click is easy to make.
            if existing.kind == kind:
                raise ValidationError(
                    "You've already super liked this person."
                    if kind == LikeType.SUPER_LIKE else
                    "You've already liked this person."
                )
            # Upgrading like -> super like is allowed and costs a super like.
            if not (existing.kind == LikeType.LIKE and kind == LikeType.SUPER_LIKE):
                raise ValidationError("You have already swiped on this person.")

        if kind == LikeType.LIKE:
            QuotaService.consume(sender, "likes_used", "daily_likes")
        elif kind == LikeType.SUPER_LIKE:
            QuotaService.consume(sender, "super_likes_used", "daily_super_likes")

        score = services.matching.score_pair(str(sender.id), receiver_id)

        if existing:
            existing.kind = kind
            existing.message = message[:200]
            existing.is_rewound = False
            existing.score_at_swipe = score
            existing.seen_by_receiver = False
            existing.save(update_fields=["kind", "message", "is_rewound",
                                         "score_at_swipe", "seen_by_receiver", "updated_at"])
            like = existing
        else:
            like = Like.objects.create(
                sender=sender, receiver_id=receiver_id, kind=kind,
                message=message[:200], source=source, score_at_swipe=score,
            )

        if kind == LikeType.PASS:
            publish(Event.PASS_SENT, {
                "sender_id": str(sender.id), "receiver_id": receiver_id,
            }, actor_id=sender.id)
            return {"matched": False, "kind": kind, "match_id": None,
                    "quota": QuotaService.snapshot(sender)}

        event = Event.SUPER_LIKE_SENT if kind == LikeType.SUPER_LIKE else Event.LIKE_SENT
        publish(event, {
            "like_id": str(like.id),
            "sender_id": str(sender.id),
            "receiver_id": receiver_id,
            "kind": kind,
            "message": like.message,
            "score": score,
        }, actor_id=sender.id)

        # Reciprocity check is owned by matches; we only ask whether it happened.
        reciprocal = Like.objects.filter(
            sender_id=receiver_id, receiver=sender,
            kind__in=[LikeType.LIKE, LikeType.SUPER_LIKE], is_rewound=False,
        ).exists()

        match_id = None
        if reciprocal:
            match = services.matches.create_match(
                str(sender.id), receiver_id,
                origin="super_like" if kind == LikeType.SUPER_LIKE else "mutual_like",
            )
            match_id = match["id"] if match else None

        return {
            "matched": bool(match_id),
            "match_id": match_id,
            "kind": kind,
            "quota": QuotaService.snapshot(sender),
        }

    @staticmethod
    @transaction.atomic
    def rewind(user):
        """Undo the most recent swipe. Premium entitlement."""
        if not services.subscriptions.has_entitlement(str(user.id), "rewind"):
            raise QuotaExceeded("Rewind is a premium feature.")
        QuotaService.consume(user, "rewinds_used", "daily_rewinds")

        last = Like.objects.filter(sender=user, is_rewound=False).order_by("-created_at").first()
        if not last:
            raise NotFound("There is nothing to undo.")

        if services.matches.are_matched(str(user.id), str(last.receiver_id)):
            raise ValidationError("You cannot undo a swipe that became a match.")

        last.is_rewound = True
        last.save(update_fields=["is_rewound", "updated_at"])
        return {"receiver_id": str(last.receiver_id), "kind": last.kind,
                "quota": QuotaService.snapshot(user)}

    @staticmethod
    def swiped_ids(user_id, include_rewound=False):
        """Everyone this member has already judged — discovery excludes these."""
        qs = Like.objects.filter(sender_id=user_id)
        if not include_rewound:
            qs = qs.filter(is_rewound=False)
        return list(qs.values_list("receiver_id", flat=True))

    @staticmethod
    def admirer_ids(user_id, unseen_only=False):
        qs = Like.objects.filter(
            receiver_id=user_id,
            kind__in=[LikeType.LIKE, LikeType.SUPER_LIKE],
            is_rewound=False,
        )
        if unseen_only:
            qs = qs.filter(seen_by_receiver=False)
        return list(qs.order_by("-created_at").values_list("sender_id", flat=True))

    @staticmethod
    def mark_admirers_seen(user_id):
        # Only positive intent is "seen" — a pass was never shown to the receiver.
        return Like.objects.filter(
            receiver_id=user_id,
            kind__in=[LikeType.LIKE, LikeType.SUPER_LIKE],
            is_rewound=False,
            seen_by_receiver=False,
        ).update(seen_by_receiver=True)


def _remaining(limit, used):
    return None if limit is None else max(limit - used, 0)
