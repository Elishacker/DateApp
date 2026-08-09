"""View mixins used by the server-rendered modules."""
from django.contrib import messages
from django.contrib.auth.mixins import AccessMixin, LoginRequiredMixin
from django.shortcuts import redirect
from rest_framework.response import Response

from .registry import services


class OnboardingRequiredMixin(LoginRequiredMixin):
    """Funnels half-registered users back into the onboarding wizard."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not request.user.has_completed_onboarding:
            return redirect("onboarding:wizard")
        return super().dispatch(request, *args, **kwargs)


class VerifiedRequiredMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not request.user.is_email_verified:
            messages.warning(request, "Please verify your email address to continue.")
            return redirect("authentication:verify_email_notice")
        return super().dispatch(request, *args, **kwargs)


class CapabilityRequiredMixin(AccessMixin):
    """Gate a page on one capability.

        class ReportQueueView(CapabilityRequiredMixin, TemplateView):
            required_capability = Capability.REVIEW_REPORTS

    Anonymous users are redirected to sign in; signed-in users without the
    capability get a 403 rather than a redirect loop.
    """

    required_capability = None
    permission_denied_message = "You do not have permission to view this page."

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        if self.required_capability is None:
            raise ValueError(
                f"{type(self).__name__} must set `required_capability`."
            )

        if not services.accounts.has_capability(
            str(request.user.id), self.required_capability
        ):
            self.raise_exception = True      # 403, never a redirect
            return self.handle_no_permission()

        return super().dispatch(request, *args, **kwargs)


class StaffAreaMixin(AccessMixin):
    """Any staff role. Prefer :class:`CapabilityRequiredMixin` where possible."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not services.accounts.is_staff_member(str(request.user.id)):
            self.raise_exception = True
            return self.handle_no_permission()
        return super().dispatch(request, *args, **kwargs)


class OwnerQuerySetMixin:
    """Restricts list/detail querysets to rows owned by the requester."""

    owner_field = "user"

    def get_queryset(self):
        return super().get_queryset().filter(**{self.owner_field: self.request.user})


class ServiceResponseMixin:
    """Uniform ``{"success": true, "data": ...}`` envelope for API views."""

    @staticmethod
    def ok(data=None, message=None, status=200):
        payload = {"success": True, "data": data if data is not None else {}}
        if message:
            payload["message"] = message
        return Response(payload, status=status)
