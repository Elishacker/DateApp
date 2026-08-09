"""Notification inbox pages."""
from django.contrib import messages as flash
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import redirect
from django.views.generic import TemplateView, View

from .services import NotificationService

#: Filter key -> (label, kinds included). Empty tuple means "everything".
#:
#: Engagement only. Account and security records are retained but live on their
#: own pages — see INBOX_KINDS in services.py for why.
FILTERS = (
    ("all", "All", ()),
    ("likes", "Likes", ("like", "super_like")),
    ("matches", "Matches", ("match",)),
    ("messages", "Messages", ("message",)),
)


class InboxView(LoginRequiredMixin, TemplateView):
    template_name = "notifications/inbox.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user_id = str(self.request.user.id)

        active = self.request.GET.get("filter", "all")
        kinds = next((k for key, _, k in FILTERS if key == active), ())

        rows = NotificationService.list_for(user_id, limit=100, kinds=kinds or None)

        context["notifications"] = [NotificationService.serialize(n) for n in rows]
        context["has_notifications"] = bool(rows)
        context["unread_count"] = NotificationService.unread_count(user_id)
        context["filters"] = [
            {"key": key, "label": label, "is_active": key == active}
            for key, label, _ in FILTERS
        ]
        context["empty_message"] = (
            "No likes or messages yet. They'll show up here as they happen."
        )
        context["footnote"] = (
            "Security alerts and receipts are emailed to you and kept on your "
            "Security and Payments pages."
        )
        return context


class MarkReadView(LoginRequiredMixin, View):
    def post(self, request, pk=None):
        count = NotificationService.mark_read(str(request.user.id), pk)
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"success": True, "marked": count})
        return redirect("notifications:inbox")


class DeleteNotificationView(LoginRequiredMixin, View):
    """Dismiss a single notification.

    POST-only, so it cannot be triggered by a link prefetch or a stray GET.
    The swipe gesture calls this over fetch; without JavaScript the same
    button submits the form and the page reloads.
    """

    def post(self, request, pk):
        user_id = str(request.user.id)
        deleted = NotificationService.delete(user_id, pk)

        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse(
                {
                    "success": bool(deleted),
                    "unread_count": NotificationService.unread_count(user_id),
                },
                status=200 if deleted else 404,
            )

        if deleted:
            flash.success(request, "Notification deleted.")
        # Deliberately not bouncing off HTTP_REFERER: that header is caller
        # controlled and would turn this into an open redirect.
        return redirect("notifications:inbox")


class ClearInboxView(LoginRequiredMixin, View):
    def post(self, request):
        count = NotificationService.clear_inbox(str(request.user.id))
        flash.success(
            request,
            f"Cleared {count} notification{'s' if count != 1 else ''}."
            if count else "There was nothing to clear.",
        )
        return redirect("notifications:inbox")


class UnreadCountView(LoginRequiredMixin, View):
    """Polled by the navbar badge when the WebSocket is unavailable."""

    def get(self, request):
        return JsonResponse({
            "success": True,
            "count": NotificationService.unread_count(str(request.user.id)),
        })
