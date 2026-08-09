"""Notifications REST endpoints."""
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.common.mixins import ServiceResponseMixin
from apps.common.registry import services


class NotificationListView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        unread_only = request.query_params.get("unread") == "true"
        limit = min(int(request.query_params.get("limit", 50)), 100)
        user_id = str(request.user.id)
        return self.ok({
            "unread_count": services.notifications.get_unread_count(user_id),
            "results": services.notifications.list_notifications(user_id, unread_only, limit),
        })

    def post(self, request):
        """Mark all (or one) as read."""
        count = services.notifications.mark_read(
            str(request.user.id), request.data.get("notification_id")
        )
        return self.ok({"marked": count}, message="Marked as read.")


class BadgeCountView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_id = str(request.user.id)
        return self.ok({
            "notifications": services.notifications.get_unread_count(user_id),
            "messages": services.chat.count_unread_conversations(user_id),
            "admirers": services.likes.count_admirers(user_id, unseen_only=True),
            "matches": services.matches.count_matches(user_id),
        })
