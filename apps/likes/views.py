"""Server-rendered likes pages."""
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from apps.common.registry import services


class SentLikesView(LoginRequiredMixin, TemplateView):
    """Everyone this member has liked, and whether it went anywhere."""

    template_name = "likes/sent.html"

    def get_context_data(self, **kwargs):
        from .models import Like, LikeType

        context = super().get_context_data(**kwargs)
        user_id = str(self.request.user.id)

        likes = Like.objects.filter(
            sender=self.request.user,
            kind__in=[LikeType.LIKE, LikeType.SUPER_LIKE],
            is_rewound=False,
        ).order_by("-created_at")[:60]

        receiver_ids = [str(like.receiver_id) for like in likes]
        refs = services.accounts.get_user_refs(receiver_ids)

        rows = []
        for like in likes:
            ref = refs.get(str(like.receiver_id))
            if not ref:
                continue
            is_match = services.matches.are_matched(user_id, str(like.receiver_id))
            rows.append({
                "user": ref,
                "kind": like.kind,
                "is_super_like": like.kind == LikeType.SUPER_LIKE,
                "score": like.score_at_swipe,
                "sent_at": like.created_at,
                "is_match": is_match,
                "status_label": "Matched" if is_match else "Waiting",
            })

        sent = services.likes.count_sent_by_kind(user_id)
        context["rows"] = rows
        context["total"] = sent["total"]
        context["like_count"] = sent["likes"]
        context["super_like_count"] = sent["super_likes"]
        context["breakdown"] = " · ".join(
            part for part in (
                f"{sent['likes']} like{'s' if sent['likes'] != 1 else ''}" if sent["likes"] else "",
                f"{sent['super_likes']} super like"
                f"{'s' if sent['super_likes'] != 1 else ''}" if sent["super_likes"] else "",
            ) if part
        )
        context["matched_count"] = sum(1 for r in rows if r["is_match"])
        return context


class QuotaView(LoginRequiredMixin, TemplateView):
    template_name = "likes/quota.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["quota"] = services.likes.get_quota(str(self.request.user.id))
        context["plan"] = services.subscriptions.get_current_plan(str(self.request.user.id))
        return context
