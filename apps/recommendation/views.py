"""Recommendation pages."""
from django.views.generic import TemplateView

from apps.common.mixins import OnboardingRequiredMixin
from apps.common.registry import services


class RecommendationsView(OnboardingRequiredMixin, TemplateView):
    template_name = "recommendation/sets.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        sets = services.recommendation.get_all_sets(str(self.request.user.id))

        # Drop empty sets here so the template never has to test for them.
        context["sets"] = [s for s in sets if s["cards"]]
        context["has_sets"] = bool(context["sets"])
        context["empty_message"] = (
            "We're still learning what you like. Swipe a few profiles and come back."
        )
        return context


class TopPicksView(OnboardingRequiredMixin, TemplateView):
    template_name = "recommendation/top_picks.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user_id = str(self.request.user.id)
        context["cards"] = services.recommendation.get_set(user_id, "top_picks", limit=10)
        context["has_cards"] = bool(context["cards"])
        context["is_premium"] = services.subscriptions.is_premium(user_id)
        context["empty_message"] = "No picks yet — check back tomorrow."
        return context
