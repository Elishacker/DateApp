"""REST wizard, used by the mobile client."""
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.common.mixins import ServiceResponseMixin

from .models import OnboardingStep
from .serializers import (
    IdentitySerializer,
    InterestsSerializer,
    LocationSerializer,
    PreferencesSerializer,
)
from .services import OnboardingService


class OnboardingStateView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return self.ok(OnboardingService.state(request.user))


class OnboardingStepView(ServiceResponseMixin, APIView):
    """POST /api/v1/onboarding/step/<key>/ — submit one step."""

    permission_classes = [IsAuthenticated]

    HANDLERS = {
        "welcome": (None, lambda user, data: OnboardingService._advance(user, OnboardingStep.WELCOME)),
        "identity": (IdentitySerializer, lambda user, data: OnboardingService.submit_identity(user, **data)),
        "photos": (None, lambda user, data: OnboardingService.submit_photos(user)),
        "interests": (InterestsSerializer, lambda user, data: OnboardingService.submit_interests(user, data["interests"])),
        "preferences": (PreferencesSerializer, lambda user, data: OnboardingService.submit_preferences(user, **data)),
        "location": (LocationSerializer, lambda user, data: OnboardingService.submit_location(user, **data)),
    }

    def post(self, request, key):
        entry = self.HANDLERS.get(key)
        if not entry:
            return self.ok(message=f"Unknown step '{key}'.", status=400)

        serializer_class, handler = entry
        data = {}
        if serializer_class:
            serializer = serializer_class(data=request.data)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data

        handler(request.user, data)
        return self.ok(OnboardingService.state(request.user), message="Step saved.")


class OnboardingSkipView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        state = OnboardingService.state(request.user)
        OnboardingService.skip_step(request.user, state["step_number"])
        return self.ok(OnboardingService.state(request.user), message="Step skipped.")
