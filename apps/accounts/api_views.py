"""REST endpoints owned by the accounts service."""
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.mixins import ServiceResponseMixin

from .models import Device
from .serializers import (
    DeactivateSerializer,
    DeviceSerializer,
    UserSerializer,
    UserSettingsSerializer,
    UserUpdateSerializer,
)
from .services import AccountService, DeviceService, SettingsService


class MeView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return self.ok(UserSerializer(request.user).data)

    def patch(self, request):
        serializer = UserUpdateSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return self.ok(UserSerializer(request.user).data, message="Account updated.")


class AccountSettingsView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        row = SettingsService.get_or_create(request.user)
        return self.ok(UserSettingsSerializer(row).data)

    def patch(self, request):
        row = SettingsService.get_or_create(request.user)
        serializer = UserSettingsSerializer(row, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return self.ok(serializer.data, message="Settings saved.")


class DeviceViewSet(ServiceResponseMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = DeviceSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Device.objects.filter(user=self.request.user).order_by("-last_seen_at")

    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        DeviceService.revoke(request.user, pk)
        return self.ok(message="Device signed out.")

    @action(detail=True, methods=["post"])
    def trust(self, request, pk=None):
        DeviceService.trust(request.user, pk)
        return self.ok(message="Device marked as trusted.")

    @action(detail=False, methods=["post"])
    def revoke_others(self, request):
        current = request.session.get("device_fingerprint")
        qs = self.get_queryset().exclude(fingerprint=current or "")
        count = qs.count()
        for device in qs:
            device.revoke()
        return self.ok({"revoked": count}, message=f"{count} other device(s) signed out.")


class DeactivateAccountView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = DeactivateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        AccountService.deactivate(request.user.id, serializer.validated_data.get("reason", ""))
        return self.ok(message="Your account is now hidden. Log in again to reactivate.")


class DeleteAccountView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = DeactivateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        AccountService.request_deletion(request.user.id)
        return self.ok(
            message="Deletion scheduled. You have 30 days to change your mind.",
            status=status.HTTP_202_ACCEPTED,
        )
