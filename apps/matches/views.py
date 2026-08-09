"""Server-rendered match list and detail."""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import redirect
from django.views.generic import TemplateView, View

from apps.common.exceptions import ZynoraError
from apps.common.mixins import OnboardingRequiredMixin
from apps.common.registry import services

from .models import MatchStatus
from .services import MatchService


class MatchListView(OnboardingRequiredMixin, TemplateView):
    template_name = "matches/list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user_id = str(self.request.user.id)

        matches = MatchService.list_for_user(user_id, MatchStatus.ACTIVE)
        rows = MatchService.build_match_rows(user_id, list(matches))

        # Split here so the template only iterates two prepared lists.
        context["new_matches"] = [r for r in rows if r["is_new"]]
        context["conversations"] = [r for r in rows if not r["is_new"]]
        context["total"] = len(rows)
        context["has_matches"] = bool(rows)
        context["empty_message"] = (
            "No matches yet. Keep swiping — your next one is out there."
        )
        return context


class MatchDetailView(OnboardingRequiredMixin, TemplateView):
    template_name = "matches/detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user_id = str(self.request.user.id)

        try:
            match = MatchService.get_for_user(self.kwargs["pk"], user_id)
        except ZynoraError as exc:
            raise Http404 from exc

        other_id = str(match.other_user_id(user_id))
        explanation = services.matching.explain_pair(user_id, other_id) or {}

        context.update({
            "match_id": str(match.id),
            "person": services.accounts.get_user_ref(other_id),
            "card": services.profiles.get_public_card(other_id, viewer_id=user_id),
            "matched_at": match.matched_at,
            "compatibility_score": match.compatibility_score,
            "shared_interests": explanation.get("shared_interests", []),
            "distance_km": explanation.get("distance_km"),
            "score_reasons": self._reasons(explanation.get("dimensions", {})),
            "conversation_id": services.chat.get_or_create_conversation(
                str(match.id), [user_id, other_id]
            ),
        })
        return context

    @staticmethod
    def _reasons(dimensions):
        """Turn raw dimension scores into human sentences — view work, not template work."""
        labels = {
            "interests": "You share a lot of interests",
            "distance": "You're close by",
            "age": "You're in each other's age range",
            "goals": "You want the same kind of relationship",
            "lifestyle": "Your lifestyles line up",
            "activity": "They're active on Zynora",
        }
        return [labels[key] for key, value in dimensions.items()
                if key in labels and value >= 0.7]


class UnmatchView(LoginRequiredMixin, View):
    def post(self, request, pk):
        try:
            MatchService.unmatch(request.user, pk, request.POST.get("reason", ""))
            messages.info(request, "You are no longer matched.")
        except ZynoraError as exc:
            messages.error(request, exc.message)
        return redirect("matches:list")
