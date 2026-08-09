"""Public contract of the recommendation service."""
from apps.common.interface import ModuleInterface

from .models import Recommendation, RecommendationSet
from .services import RecommendationService


class RecommendationInterface(ModuleInterface):
    name = "recommendation"
    depends_on = ("accounts", "profiles", "matching", "likes", "matches", "reports")

    def get_set(self, user_id, set_name="top_picks", limit=10):
        return RecommendationService.get_set(user_id, set_name, limit)

    def get_all_sets(self, user_id):
        return RecommendationService.all_sets(user_id)

    def rebuild(self, user_id):
        return RecommendationService.build_all(user_id)

    def invalidate(self, user_id):
        return RecommendationService.invalidate(user_id)

    def mark_acted(self, user_id, candidate_id):
        return RecommendationService.mark_acted(user_id, candidate_id)

    def available_sets(self):
        return [{"key": value, "label": label} for value, label in RecommendationSet.choices]

    def effectiveness(self):
        return RecommendationService.effectiveness()

    def count_for(self, user_id):
        return Recommendation.objects.filter(user_id=user_id).count()


service = RecommendationInterface()
