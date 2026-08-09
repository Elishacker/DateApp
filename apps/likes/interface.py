"""Public contract of the likes service."""
from apps.common.interface import ModuleInterface

from .models import Like, LikeType
from .services import LikeService, QuotaService


class LikesInterface(ModuleInterface):
    name = "likes"
    depends_on = ("accounts", "matching", "matches", "subscriptions", "reports")

    # ---- writes -------------------------------------------------------------
    def swipe(self, sender_id, receiver_id, kind="like", message="", source="discovery"):
        """Record a swipe. Returns ``{matched, match_id, kind, quota}``."""
        from django.contrib.auth import get_user_model

        sender = get_user_model().objects.filter(id=sender_id).first()
        if not sender:
            return None
        return LikeService.swipe(sender, receiver_id, kind, message, source)

    def rewind(self, user_id):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.filter(id=user_id).first()
        if not user:
            return None
        return LikeService.rewind(user)

    # ---- reads --------------------------------------------------------------
    def has_liked(self, sender_id, receiver_id):
        return Like.objects.filter(
            sender_id=sender_id, receiver_id=receiver_id,
            kind__in=[LikeType.LIKE, LikeType.SUPER_LIKE], is_rewound=False,
        ).exists()

    def has_swiped(self, sender_id, receiver_id):
        return Like.objects.filter(
            sender_id=sender_id, receiver_id=receiver_id, is_rewound=False
        ).exists()

    def is_mutual(self, user_a, user_b):
        positive = [LikeType.LIKE, LikeType.SUPER_LIKE]
        return (
            Like.objects.filter(sender_id=user_a, receiver_id=user_b,
                                kind__in=positive, is_rewound=False).exists()
            and Like.objects.filter(sender_id=user_b, receiver_id=user_a,
                                    kind__in=positive, is_rewound=False).exists()
        )

    def get_swiped_ids(self, user_id):
        """Everyone judged in any direction."""
        return [str(pk) for pk in LikeService.swiped_ids(user_id)]

    def get_passed_ids(self, user_id):
        """Only the people passed on — the ones discovery should hide.

        Liking someone deliberately does *not* remove them from the feed: you
        stay able to see who you liked, and the card shows a liked state instead
        of vanishing.
        """
        return [
            str(pk) for pk in Like.objects.filter(
                sender_id=user_id, kind=LikeType.PASS, is_rewound=False
            ).values_list("receiver_id", flat=True)
        ]

    def get_liked_map(self, user_id, candidate_ids=None):
        """``{candidate_id: "like"|"super_like"}`` for rendering liked state."""
        qs = Like.objects.filter(
            sender_id=user_id,
            kind__in=[LikeType.LIKE, LikeType.SUPER_LIKE],
            is_rewound=False,
        )
        if candidate_ids is not None:
            qs = qs.filter(receiver_id__in=list(candidate_ids))
        return {str(receiver): kind for receiver, kind in qs.values_list("receiver_id", "kind")}

    def get_admirer_ids(self, user_id, unseen_only=False):
        return [str(pk) for pk in LikeService.admirer_ids(user_id, unseen_only)]

    def count_admirers(self, user_id, unseen_only=False):
        qs = Like.objects.filter(
            receiver_id=user_id, kind__in=[LikeType.LIKE, LikeType.SUPER_LIKE], is_rewound=False
        )
        if unseen_only:
            qs = qs.filter(seen_by_receiver=False)
        return qs.count()

    def count_admirers_by_kind(self, user_id, unseen_only=False):
        """``{likes, super_likes, total}`` — every incoming intent, tallied.

        A plain like and a super like are different signals, so they are counted
        separately rather than folded into one number. Callers that only want a
        badge read ``total``.
        """
        from django.db.models import Count

        qs = Like.objects.filter(
            receiver_id=user_id, kind__in=[LikeType.LIKE, LikeType.SUPER_LIKE], is_rewound=False
        )
        if unseen_only:
            qs = qs.filter(seen_by_receiver=False)

        tally = {row["kind"]: row["n"] for row in qs.values("kind").annotate(n=Count("id"))}
        likes = tally.get(LikeType.LIKE, 0)
        super_likes = tally.get(LikeType.SUPER_LIKE, 0)
        return {"likes": likes, "super_likes": super_likes, "total": likes + super_likes}

    def count_received_bulk(self, user_ids):
        """``{user_id: {likes, super_likes, total}}`` for a whole page of cards.

        One grouped query for the batch — discovery renders up to 20 cards at a
        time and must not pay a query each. Ids with no likes come back as
        zeroes rather than missing, so callers never branch on absence.
        """
        from django.db.models import Count

        user_ids = [str(u) for u in user_ids]
        counts = {uid: {"likes": 0, "super_likes": 0, "total": 0} for uid in user_ids}
        if not user_ids:
            return counts

        rows = (
            Like.objects.filter(
                receiver_id__in=user_ids,
                kind__in=[LikeType.LIKE, LikeType.SUPER_LIKE],
                is_rewound=False,
            )
            .values("receiver_id", "kind")
            .annotate(n=Count("id"))
        )
        for row in rows:
            entry = counts.get(str(row["receiver_id"]))
            if entry is None:
                continue
            key = "super_likes" if row["kind"] == LikeType.SUPER_LIKE else "likes"
            entry[key] += row["n"]
            entry["total"] += row["n"]
        return counts

    def count_sent_by_kind(self, user_id):
        """``{likes, super_likes, total}`` — everything this member has sent."""
        from django.db.models import Count

        tally = {
            row["kind"]: row["n"]
            for row in Like.objects.filter(
                sender_id=user_id,
                kind__in=[LikeType.LIKE, LikeType.SUPER_LIKE],
                is_rewound=False,
            ).values("kind").annotate(n=Count("id"))
        }
        likes = tally.get(LikeType.LIKE, 0)
        super_likes = tally.get(LikeType.SUPER_LIKE, 0)
        return {"likes": likes, "super_likes": super_likes, "total": likes + super_likes}

    def get_admirer_kinds(self, user_id, sender_ids=None):
        """``{sender_id: "like"|"super_like"}`` for rendering incoming intent."""
        qs = Like.objects.filter(
            receiver_id=user_id, kind__in=[LikeType.LIKE, LikeType.SUPER_LIKE], is_rewound=False
        )
        if sender_ids is not None:
            qs = qs.filter(sender_id__in=list(sender_ids))
        return {str(sender): kind for sender, kind in qs.values_list("sender_id", "kind")}

    def get_super_like_message(self, sender_id, receiver_id):
        like = Like.objects.filter(
            sender_id=sender_id, receiver_id=receiver_id, kind=LikeType.SUPER_LIKE
        ).first()
        return like.message if like else ""

    def get_quota(self, user_id):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.filter(id=user_id).first()
        return QuotaService.snapshot(user) if user else None

    def mark_admirers_seen(self, user_id):
        return LikeService.mark_admirers_seen(user_id)

    def reset_all_quotas(self):
        """Daily counter reset, triggered by the subscriptions beat schedule."""
        from django.utils import timezone

        from .models import SwipeQuota

        return SwipeQuota.objects.filter(
            reset_at__date__lt=timezone.now().date()
        ).update(likes_used=0, super_likes_used=0, rewinds_used=0,
                 reset_at=timezone.now())

    def purge_for_user(self, user_id):
        """Called on account deletion so no orphan intent rows remain."""
        from django.db.models import Q

        deleted, _ = Like.objects.filter(
            Q(sender_id=user_id) | Q(receiver_id=user_id)
        ).delete()
        return deleted

    def daily_stats(self, since=None):
        qs = Like.objects.all()
        if since:
            qs = qs.filter(created_at__gte=since)
        return {
            "likes": qs.filter(kind=LikeType.LIKE).count(),
            "super_likes": qs.filter(kind=LikeType.SUPER_LIKE).count(),
            "passes": qs.filter(kind=LikeType.PASS).count(),
        }


service = LikesInterface()
