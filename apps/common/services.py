"""Cross-cutting service helpers (cache keys, counters, feature flags)."""
from django.core.cache import cache


class CacheService:
    """Namespaced cache access so modules never collide on key names."""

    PREFIX = "zynora"

    @classmethod
    def key(cls, module, *parts):
        return ":".join([cls.PREFIX, module, *[str(p) for p in parts]])

    @classmethod
    def get(cls, module, *parts, default=None):
        return cache.get(cls.key(module, *parts), default)

    @classmethod
    def set(cls, module, *parts, value=None, ttl=300):
        cache.set(cls.key(module, *parts), value, ttl)
        return value

    @classmethod
    def delete(cls, module, *parts):
        cache.delete(cls.key(module, *parts))

    @classmethod
    def incr(cls, module, *parts, ttl=60):
        """Atomic-ish counter that also creates the key on first use."""
        key = cls.key(module, *parts)
        added = cache.add(key, 1, ttl)
        if added:
            return 1
        try:
            return cache.incr(key)
        except ValueError:
            cache.set(key, 1, ttl)
            return 1


class FeatureFlagService:
    """Simple runtime flags; swap the backend for a config service later."""

    DEFAULTS = {
        "video_calls": False,
        "ai_moderation": True,
        "recommendation_v2": True,
        "social_login": True,
        "mobile_money": True,
    }

    @classmethod
    def enabled(cls, name):
        cached = CacheService.get("flags", name)
        if cached is not None:
            return bool(cached)
        return cls.DEFAULTS.get(name, False)

    @classmethod
    def set(cls, name, value):
        CacheService.set("flags", name, value=bool(value), ttl=86400)
