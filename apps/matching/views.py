"""Compatibility explanation page."""
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.views.generic import TemplateView

from apps.common.registry import services

#: Dimension key -> (label, sentence when strong, sentence when weak)
DIMENSION_COPY = {
    "interests": ("Shared interests", "You like a lot of the same things",
                  "You have different interests"),
    "distance": ("Distance", "You're close to each other", "You're far apart"),
    "age": ("Age", "You're well inside each other's range", "There's an age gap"),
    "goals": ("Relationship goals", "You want the same thing", "You want different things"),
    "lifestyle": ("Lifestyle", "Your habits line up", "Your lifestyles differ"),
    "activity": ("Activity", "They're active and complete their profile",
                 "They're not very active"),
    "education": ("Education", "Their education matches your preference",
                  "Different educational background"),
}


class ExplainView(LoginRequiredMixin, TemplateView):
    """Shows *why* two people scored the way they did."""

    template_name = "matching/explain.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user_id = str(self.request.user.id)
        other_id = str(self.kwargs["user_id"])

        breakdown = services.matching.explain_pair(user_id, other_id)
        if not breakdown:
            raise Http404

        # All formatting happens here so the template just loops and prints.
        rows = []
        for key, value in breakdown["dimensions"].items():
            label, strong, weak = DIMENSION_COPY.get(key, (key.title(), "", ""))
            percent = int(value * 100)
            rows.append({
                "label": label,
                "percent": percent,
                "sentence": strong if value >= 0.6 else weak,
                "is_strong": value >= 0.6,
            })
        rows.sort(key=lambda r: r["percent"], reverse=True)

        context.update({
            "person": services.accounts.get_user_ref(other_id),
            "score": breakdown["score"],
            "score_label": self._label(breakdown["score"]),
            "distance_km": breakdown["distance_km"],
            "shared_interests": breakdown["shared_interests"],
            "shared_count": len(breakdown["shared_interests"]),
            "dimensions": rows,
        })
        return context

    @staticmethod
    def _label(score):
        if score >= 85:
            return "Exceptional match"
        if score >= 70:
            return "Great match"
        if score >= 55:
            return "Good match"
        return "Worth a look"
