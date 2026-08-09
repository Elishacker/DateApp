"""Likes REST endpoints."""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.common.mixins import ServiceResponseMixin
from apps.common.permissions import IsOnboarded
from apps.common.registry import services

from .serializers import SwipeSerializer


class SwipeAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated, IsOnboarded]

    def post(self, request):
        serializer = SwipeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        result = services.likes.swipe(
            str(request.user.id), str(data["user_id"]),
            data.get("kind", "like"), data.get("message", ""),
            data.get("source", "discovery"),
        )
        services.discovery.invalidate_feed(str(request.user.id))

        payload = dict(result)
        if result["matched"]:
            payload["matched_with"] = services.accounts.get_user_ref(str(data["user_id"]))

        return self.ok(
            payload,
            message="It's a match!" if result["matched"] else "Swipe recorded.",
            status=status.HTTP_201_CREATED,
        )


class RewindAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated, IsOnboarded]

    def post(self, request):
        result = services.likes.rewind(str(request.user.id))
        services.discovery.invalidate_feed(str(request.user.id))
        return self.ok(result, message="Last swipe undone.")


class QuotaAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return self.ok(services.likes.get_quota(str(request.user.id)))


class AdmirerCountAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_id = str(request.user.id)
        return self.ok({
            "total": services.likes.count_admirers(user_id),
            "unseen": services.likes.count_admirers(user_id, unseen_only=True),
            "unlocked": services.subscriptions.has_entitlement(user_id, "see_who_likes_you"),
        })
