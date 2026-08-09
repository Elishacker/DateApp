"""Verification REST endpoints."""
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.common.mixins import ServiceResponseMixin
from apps.common.permissions import CanReviewVerification
from apps.common.registry import services

from .models import VerificationKind
from .serializers import (
    PhoneConfirmSerializer,
    PhoneStartSerializer,
    SelfieUploadSerializer,
    VerificationDecisionSerializer,
)
from .services import VerificationService


class VerificationStatusAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return self.ok(VerificationService.status_for(str(request.user.id)))


class SelfieUploadAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        """Returns the pose the member must reproduce."""
        return self.ok({"pose": VerificationService.new_challenge()})

    def post(self, request):
        serializer = SelfieUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        request_obj = VerificationService.submit_photo(
            request.user, serializer.validated_data["photo"],
            serializer.validated_data.get("pose", ""),
            serializer.validated_data.get("kind", VerificationKind.SELFIE),
        )
        return self.ok({"request_id": str(request_obj.id), "status": request_obj.status},
                       message="Submitted for review.")


class PhoneVerificationAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PhoneStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = VerificationService.start_phone_verification(
            request.user, serializer.validated_data["phone"]
        )
        return self.ok(result, message="Verification code sent.")

    def put(self, request):
        serializer = PhoneConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        VerificationService.confirm_phone(request.user, serializer.validated_data["code"])
        return self.ok(message="Phone verified.")


class VerificationQueueAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated, CanReviewVerification]

    def get(self, request):
        return self.ok({"queue": services.verification.pending_queue()})

    def post(self, request):
        serializer = VerificationDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = services.verification.decide(
            str(data["request_id"]), data["approved"],
            str(request.user.id), data.get("reason", ""),
        )
        return self.ok(result, message="Decision recorded.")
