"""Role context for the server-rendered UI.

The staff navigation is computed here, not in the sidebar template. That keeps
role logic out of the HTML entirely — the template just loops over whatever list
it is handed, which is empty for an ordinary member.
"""
import logging

from django.urls import NoReverseMatch, reverse

from apps.common.registry import services

logger = logging.getLogger(__name__)


def role_context(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {"is_staff_area": False, "staff_nav": [], "capabilities": []}

    user_id = str(user.id)
    try:
        role = services.accounts.get_role(user_id) or {}
        nav = services.accounts.get_staff_navigation(user_id)
    except Exception:  # noqa: BLE001 - navigation must never break a page render
        logger.exception("could not resolve role context for %s", user_id)
        return {"is_staff_area": False, "staff_nav": [], "capabilities": []}

    # Resolve URLs here so the template needs no {% url %} lookup on a variable.
    resolved = []
    for item in nav:
        try:
            resolved.append({**item, "url": reverse(item["url_name"])})
        except NoReverseMatch:
            logger.warning("staff nav entry %s has no URL", item["url_name"])

    return {
        "is_staff_area": role.get("is_staff_area", False),
        "staff_nav": resolved,
        "capabilities": role.get("capabilities", []),
        "role_label": role.get("label", ""),
    }
