"""Verification pages."""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import FormView, TemplateView, View

from apps.common.constants import Capability
from apps.common.exceptions import ZynoraError
from apps.common.mixins import CapabilityRequiredMixin
from apps.common.registry import services

from .forms import PhoneCodeForm, PhoneStartForm, SelfieForm
from .models import VerificationKind
from .services import VerificationService


class VerificationHomeView(LoginRequiredMixin, TemplateView):
    template_name = "verification/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status"] = VerificationService.status_for(str(self.request.user.id))
        return context


class SelfieVerificationView(LoginRequiredMixin, FormView):
    template_name = "verification/selfie.html"
    form_class = SelfieForm
    success_url = reverse_lazy("verification:home")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        pose = self.request.session.get("verification_pose")
        if not pose:
            pose = VerificationService.new_challenge()
            self.request.session["verification_pose"] = pose
        context["pose"] = pose
        return context

    def form_valid(self, form):
        try:
            VerificationService.submit_photo(
                self.request.user,
                form.cleaned_data["photo"],
                self.request.session.get("verification_pose", ""),
                VerificationKind.SELFIE,
            )
        except ZynoraError as exc:
            form.add_error(None, exc.message)
            return self.form_invalid(form)

        self.request.session.pop("verification_pose", None)
        messages.success(
            self.request, "Photo submitted. We usually review within a few hours."
        )
        return super().form_valid(form)


class IdentityVerificationView(LoginRequiredMixin, FormView):
    template_name = "verification/identity.html"
    form_class = SelfieForm
    success_url = reverse_lazy("verification:home")

    def form_valid(self, form):
        try:
            VerificationService.submit_photo(
                self.request.user, form.cleaned_data["photo"], "",
                VerificationKind.GOVERNMENT_ID,
            )
        except ZynoraError as exc:
            form.add_error(None, exc.message)
            return self.form_invalid(form)
        messages.success(self.request, "ID submitted for review.")
        return super().form_valid(form)


class PhoneVerificationView(LoginRequiredMixin, FormView):
    template_name = "verification/phone.html"
    form_class = PhoneStartForm
    success_url = reverse_lazy("verification:phone_confirm")

    def form_valid(self, form):
        try:
            VerificationService.start_phone_verification(
                self.request.user, form.cleaned_data["phone"]
            )
        except ZynoraError as exc:
            form.add_error(None, exc.message)
            return self.form_invalid(form)
        messages.info(self.request, "We sent you a code by SMS.")
        return super().form_valid(form)


class PhoneConfirmView(LoginRequiredMixin, FormView):
    template_name = "verification/phone_confirm.html"
    form_class = PhoneCodeForm
    success_url = reverse_lazy("verification:home")

    def form_valid(self, form):
        try:
            VerificationService.confirm_phone(self.request.user, form.cleaned_data["code"])
        except ZynoraError as exc:
            form.add_error("code", exc.message)
            return self.form_invalid(form)
        messages.success(self.request, "Your phone number is verified.")
        return super().form_valid(form)


class VerificationQueueView(CapabilityRequiredMixin, TemplateView):
    """Staff review console for submitted verifications."""

    required_capability = Capability.REVIEW_VERIFICATION
    template_name = "verification/queue.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        queue = services.verification.pending_queue()
        refs = services.accounts.get_user_refs([row["user_id"] for row in queue])

        context["rows"] = [
            {**row, "member": refs.get(row["user_id"])}
            for row in queue if refs.get(row["user_id"])
        ]
        context["has_rows"] = bool(context["rows"])
        context["stats"] = services.verification.stats()
        context["empty_message"] = "Nothing waiting for review."
        return context


class VerificationDecideView(CapabilityRequiredMixin, View):
    required_capability = Capability.REVIEW_VERIFICATION

    def post(self, request, request_id):
        approved = request.POST.get("decision") == "approve"
        services.verification.decide(
            str(request_id), approved, str(request.user.id),
            request.POST.get("reason", ""),
        )
        messages.success(request, "Approved." if approved else "Rejected.")
        return redirect("verification:queue")


class ResendPhoneCodeView(LoginRequiredMixin, View):
    def post(self, request):
        phone = request.user.phone
        if not phone:
            messages.error(request, "Add a phone number first.")
            return redirect("verification:phone")
        try:
            VerificationService.start_phone_verification(request.user, phone)
            messages.info(request, "A new code is on its way.")
        except ZynoraError as exc:
            messages.warning(request, exc.message)
        return redirect("verification:phone_confirm")
