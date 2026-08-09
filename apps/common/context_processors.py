"""Template context available on every server-rendered page."""
from django.conf import settings


def site_context(request):
    return {
        "SITE": settings.ZYNORA,
        "DEBUG": settings.DEBUG,
    }


#: URL namespace -> the navigation section it belongs to. Anything not listed
#: highlights nothing, which is the right answer for one-off settings pages.
_SECTION_BY_NAMESPACE = {
    "discovery": "discover",
    "recommendation": "discover",
    "matching": "discover",
    "matches": "matches",
    "chat": "messages",
    "likes": "likes",
    "notifications": "notifications",
    "profiles": "profile",
    "accounts": "profile",
    "subscriptions": "profile",
    "security": "profile",
    "verification": "profile",
}

#: Views whose namespace alone would point at the wrong section. "Likes you"
#: is served by discovery but is its own destination in the navigation.
_SECTION_BY_VIEW = {
    "discovery:admirers": "likes",
}

#: Every section a nav control can highlight.
_SECTIONS = ("discover", "matches", "messages", "profile", "likes", "notifications")


def navigation(request):
    """Which navigation section the current page belongs to.

    Returns ``nav_is`` — a flag per section — so the sidebar and the mobile
    bottom bar mark themselves active with a presence check and no comparison.
    Working out "am I the current tab" is computation, and templates in this
    project only print.
    """
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}

    match = getattr(request, "resolver_match", None)
    active = ""
    if match:
        active = _SECTION_BY_VIEW.get(
            match.view_name, _SECTION_BY_NAMESPACE.get(match.app_name, "")
        )
    return {
        "nav_active": active,
        "nav_is": {section: section == active for section in _SECTIONS},
    }
