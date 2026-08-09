"""Public contract of the discovery service."""
from apps.common.interface import ModuleInterface

from .services import DiscoveryService


class DiscoveryInterface(ModuleInterface):
    name = "discovery"
    depends_on = ("accounts", "profiles", "matching", "likes", "matches", "reports")

    def get_feed(self, user_id, limit=20, refresh=False):
        return DiscoveryService.build_feed(user_id, limit=limit, refresh=refresh)

    def get_nearby(self, user_id, limit=20, radius_km=50):
        return DiscoveryService.nearby(user_id, limit=limit, radius_km=radius_km)

    def get_online(self, user_id, limit=20):
        return DiscoveryService.online_now(user_id, limit=limit)

    def get_newest(self, user_id, limit=20):
        return DiscoveryService.newest(user_id, limit=limit)

    def get_verified(self, user_id, limit=20):
        return DiscoveryService.verified_only(user_id, limit=limit)

    def get_admirers(self, user_id, limit=30):
        return DiscoveryService.admirers(user_id, limit=limit)

    def search(self, user_id, query, scope="all", limit=40, respect_preferences=False):
        return DiscoveryService.search(
            user_id, query, scope=scope, limit=limit,
            respect_preferences=respect_preferences,
        )

    def explain_empty_feed(self, user_id):
        return DiscoveryService.explain_empty(user_id)

    def invalidate_feed(self, user_id):
        DiscoveryService.invalidate(user_id)
        return True


service = DiscoveryInterface()
