"""Navbar badge counts, available on every rendered page."""
from apps.common.registry import services


def unread_notifications(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}

    user_id = str(request.user.id)
    try:
        admirers = services.likes.count_admirers_by_kind(user_id, unseen_only=True)
        return {
            "unread_notifications": services.notifications.get_unread_count(user_id),
            "unread_messages": services.chat.count_unread_conversations(user_id),
            "unseen_admirers": admirers["total"],
            "unseen_likes": admirers["likes"],
            "unseen_super_likes": admirers["super_likes"],
            # Pre-phrased here so the sidebar prints it without building strings.
            "unseen_admirers_title": _admirers_title(admirers),
        }
    except Exception:  # noqa: BLE001 - a badge must never break page rendering
        return {}


def _admirers_title(admirers):
    parts = []
    if admirers["likes"]:
        parts.append(f"{admirers['likes']} new like{'s' if admirers['likes'] != 1 else ''}")
    if admirers["super_likes"]:
        parts.append(
            f"{admirers['super_likes']} new super like"
            f"{'s' if admirers['super_likes'] != 1 else ''}"
        )
    return " · ".join(parts) or "Nobody new has liked you yet"
