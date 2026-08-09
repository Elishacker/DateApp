"""Discovery feed pages.

The view does all the work: it picks the feed, computes labels and quota
messaging, and hands the template a flat list of card dicts.
"""
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.views.generic import TemplateView, View

from apps.common.exceptions import ZynoraError
from apps.common.mixins import OnboardingRequiredMixin
from apps.common.registry import services

from .services import DiscoveryService

#: tab key -> (label, service method name)
FEED_TABS = (
    ("for-you", "For you", "get_feed"),
    ("nearby", "Nearby", "get_nearby"),
    ("online", "Online", "get_online"),
    ("new", "New", "get_newest"),
    ("verified", "Verified", "get_verified"),
)


class FeedView(OnboardingRequiredMixin, TemplateView):
    template_name = "discovery/feed.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user_id = str(self.request.user.id)
        active = self.request.GET.get("tab", "for-you")
        if active not in {key for key, _, _ in FEED_TABS}:
            active = "for-you"

        method = next(m for key, _, m in FEED_TABS if key == active)
        cards = getattr(services.discovery, method)(user_id, limit=20)

        quota = services.likes.get_quota(user_id) or {}
        widened = sum(1 for c in cards if c.get("outside_range"))
        context.update({
            "cards": cards,
            "widened_count": widened,
            "widened_notice": (
                f"{widened} of these are further than your usual distance — "
                "there weren't enough people nearby."
            ) if widened else "",
            "card_count": len(cards),
            "has_cards": bool(cards),
            "active_tab": active,
            "tabs": [
                {"key": key, "label": label, "is_active": key == active}
                for key, label, _ in FEED_TABS
            ],
            "quota": quota,
            "quota_message": self._quota_message(quota),
            "can_rewind": services.subscriptions.has_entitlement(user_id, "rewind"),
            "empty_message": self._empty_message(active),
            # Only computed when there is nothing to show — it costs a query.
            "empty_reason": (
                services.discovery.explain_empty_feed(user_id) if not cards else None
            ),
        })
        return context

    @staticmethod
    def _quota_message(quota):
        if not quota or quota.get("is_unlimited"):
            return "Unlimited likes"
        remaining = quota.get("likes_remaining", 0)
        if remaining <= 0:
            return "You're out of likes for today — upgrade for unlimited"
        if remaining <= 5:
            return f"Only {remaining} likes left today"
        return f"{remaining} likes left today"

    @staticmethod
    def _empty_message(tab):
        return {
            "for-you": "You've seen everyone for now. Widen your preferences or check back soon.",
            "nearby": "Nobody new within range right now. Try increasing your distance.",
            "online": "No one you haven't seen is online at the moment.",
            "new": "No new members match your preferences this week.",
            "verified": "No verified members left to show right now.",
        }.get(tab, "Nothing to show right now.")


#: scope key -> label, shown as filter chips on the search page.
SEARCH_SCOPES = (
    ("all", "Everything"),
    ("name", "Name"),
    ("region", "Region"),
    ("country", "Country"),
    ("job", "Job title"),
    ("interests", "Interests"),
)


class SearchView(OnboardingRequiredMixin, TemplateView):
    """Find anyone by name, region, country, job title or interests."""

    template_name = "discovery/search.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user_id = str(self.request.user.id)

        query = (self.request.GET.get("q") or "").strip()
        scope = self.request.GET.get("scope", "all")
        if scope not in dict(SEARCH_SCOPES):
            scope = "all"
        strict = self.request.GET.get("strict") == "1"

        context["query"] = query
        context["scope"] = scope
        context["strict"] = strict
        context["scopes"] = [
            {"key": key, "label": label, "is_active": key == scope}
            for key, label in SEARCH_SCOPES
        ]
        context["facets"] = services.profiles.search_facets()

        if query:
            outcome = services.discovery.search(
                user_id, query, scope=scope, limit=48, respect_preferences=strict
            )
            context.update({
                "results": outcome["results"],
                "count": outcome["count"],
                "message": outcome["message"],
                "has_searched": True,
                "headline": (
                    f"{outcome['count']} result{'s' if outcome['count'] != 1 else ''} "
                    f"for “{query}”"
                ),
            })
        else:
            context.update({
                "results": [], "count": 0, "has_searched": False,
                "message": "",
                "headline": "Search Zynora",
            })
        return context


class AdmirersView(OnboardingRequiredMixin, TemplateView):
    """'Who likes you' — blurred for free accounts."""

    template_name = "discovery/admirers.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user_id = str(self.request.user.id)
        unlocked = services.subscriptions.has_entitlement(user_id, "see_who_likes_you")
        counts = services.likes.count_admirers_by_kind(user_id)
        total = counts["total"]

        context["unlocked"] = unlocked
        context["total"] = total
        context["like_count"] = counts["likes"]
        context["super_like_count"] = counts["super_likes"]
        context["breakdown"] = self._breakdown(counts)
        context["headline"] = (
            f"{total} {'person likes' if total == 1 else 'people like'} you"
            if total else "No likes yet — keep swiping"
        )
        if unlocked:
            context["cards"] = services.discovery.get_admirers(user_id)
            services.likes.mark_admirers_seen(user_id)
        else:
            context["cards"] = []
            context["upsell"] = "Subscribe to any paid plan to see everyone who liked you."
        return context

    @staticmethod
    def _breakdown(counts):
        """'12 likes · 3 super likes' — built here so the template only prints."""
        parts = []
        if counts["likes"]:
            parts.append(f"{counts['likes']} like{'s' if counts['likes'] != 1 else ''}")
        if counts["super_likes"]:
            parts.append(
                f"{counts['super_likes']} super like"
                f"{'s' if counts['super_likes'] != 1 else ''}"
            )
        return " · ".join(parts)


class SwipeView(LoginRequiredMixin, View):
    """AJAX endpoint behind the swipe buttons. Returns JSON for the JS layer."""

    def post(self, request):
        target = request.POST.get("user_id")
        kind = request.POST.get("kind", "like")
        message = request.POST.get("message", "")

        try:
            result = services.likes.swipe(str(request.user.id), target, kind, message)
        except ZynoraError as exc:
            return JsonResponse(
                {"success": False, "code": exc.code, "message": exc.message},
                status=exc.status_code,
            )

        DiscoveryService.invalidate(request.user.id)
        payload = {"success": True, "matched": result["matched"], "quota": result["quota"]}
        if result["matched"]:
            other = services.accounts.get_user_ref(target)
            payload["match"] = {
                "match_id": result["match_id"],
                "user": other,
                "message": f"You and {other['display_name']} liked each other!",
            }
        return JsonResponse(payload)


class RewindView(LoginRequiredMixin, View):
    def post(self, request):
        try:
            result = services.likes.rewind(str(request.user.id))
        except ZynoraError as exc:
            return JsonResponse(
                {"success": False, "code": exc.code, "message": exc.message},
                status=exc.status_code,
            )
        DiscoveryService.invalidate(request.user.id)
        return JsonResponse({"success": True, **result})


class FeedRefreshView(LoginRequiredMixin, View):
    """Fetch the next batch of cards without a full page load."""

    def get(self, request):
        cards = services.discovery.get_feed(str(request.user.id), limit=10, refresh=True)
        return JsonResponse({"success": True, "cards": cards, "count": len(cards)})
