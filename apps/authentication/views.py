"""Server-rendered authentication flow."""
import logging

from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.views.generic import FormView, TemplateView, View

from apps.common.exceptions import ZynoraError

from .forms import (
    LoginForm,
    MFAChallengeForm,
    MFAEnrolForm,
    PasswordChangeForm,
    PasswordResetForm,
    PasswordResetRequestForm,
    RegisterForm,
)
from .models import TokenPurpose
from .services import LoginService, MFAService, PasswordService, RegistrationService

logger = logging.getLogger(__name__)
User = get_user_model()

#: Session key holding the id of a user who passed the password step but not MFA.
MFA_PENDING_KEY = "mfa_pending_user"


class RegisterView(FormView):
    template_name = "authentication/register.html"
    form_class = RegisterForm
    success_url = reverse_lazy("authentication:verify_email_notice")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("discovery:feed")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        data = form.cleaned_data
        try:
            user, _ = RegistrationService.register(
                email=data["email"],
                username=data["username"],
                password=data["password"],
                first_name=data["first_name"],
                date_of_birth=data["date_of_birth"],
                accepted_terms=data["accepted_terms"],
                marketing_opt_in=data.get("marketing_opt_in", False),
                request=self.request,
            )
        except ZynoraError as exc:
            form.add_error(None, exc.message)
            return self.form_invalid(form)

        # Sign the member in immediately; the wizard gates everything else.
        login(self.request, user, backend="apps.authentication.backends.EmailOrPhoneBackend")
        LoginService.complete_login(user, self.request)
        messages.success(
            self.request,
            f"Welcome to Zynora, {user.display_name}! Check your inbox to confirm your email.",
        )
        return redirect("onboarding:wizard")


class LoginView(FormView):
    template_name = "authentication/login.html"
    form_class = LoginForm

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("discovery:feed")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        try:
            user, requires_mfa = LoginService.authenticate(
                form.cleaned_data["identifier"], form.cleaned_data["password"], self.request
            )
        except ZynoraError as exc:
            form.add_error(None, exc.message)
            return self.form_invalid(form)

        if requires_mfa:
            self.request.session[MFA_PENDING_KEY] = str(user.id)
            self.request.session["mfa_remember"] = form.cleaned_data.get("remember_me", True)
            return redirect("authentication:mfa_challenge")

        login(self.request, user, backend="apps.authentication.backends.EmailOrPhoneBackend")
        if not form.cleaned_data.get("remember_me"):
            self.request.session.set_expiry(0)
        LoginService.complete_login(user, self.request)
        return redirect(self.get_success_url())

    def get_success_url(self):
        nxt = self.request.GET.get("next")
        if nxt:
            return nxt
        user = self.request.user
        if user.is_authenticated and not user.has_completed_onboarding:
            return reverse("onboarding:wizard")
        return reverse("discovery:feed")


class MFAChallengeView(FormView):
    template_name = "authentication/mfa_challenge.html"
    form_class = MFAChallengeForm

    def dispatch(self, request, *args, **kwargs):
        if not request.session.get(MFA_PENDING_KEY):
            return redirect("authentication:login")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        user = User.objects.filter(id=self.request.session[MFA_PENDING_KEY]).first()
        if not user:
            self.request.session.pop(MFA_PENDING_KEY, None)
            return redirect("authentication:login")

        try:
            MFAService.verify(user, form.cleaned_data["code"])
        except ZynoraError as exc:
            form.add_error("code", exc.message)
            return self.form_invalid(form)

        remember = self.request.session.pop("mfa_remember", True)
        self.request.session.pop(MFA_PENDING_KEY, None)
        login(self.request, user, backend="apps.authentication.backends.EmailOrPhoneBackend")
        if not remember:
            self.request.session.set_expiry(0)
        LoginService.complete_login(user, self.request, mfa_used=True)
        return redirect("discovery:feed")


class LogoutView(View):
    def post(self, request):
        if request.user.is_authenticated:
            LoginService.logout(request.user, request)
        logout(request)
        messages.info(request, "You have been signed out.")
        return redirect("common:landing")

    def get(self, request):
        return self.post(request)


class VerifyEmailNoticeView(TemplateView):
    template_name = "authentication/verify_email_notice.html"


class VerifyEmailView(View):
    def get(self, request, token):
        try:
            user = RegistrationService.verify_email(token)
        except ZynoraError as exc:
            messages.error(request, exc.message)
            return redirect("authentication:verify_email_notice")

        messages.success(request, "Your email is confirmed. Welcome aboard!")
        if request.user.is_authenticated:
            return redirect("onboarding:wizard" if not user.has_completed_onboarding
                            else "discovery:feed")
        return redirect("authentication:login")


class ResendVerificationView(LoginRequiredMixin, View):
    def post(self, request):
        try:
            RegistrationService.resend_verification(request.user, request)
            messages.success(request, "Verification email sent.")
        except ZynoraError as exc:
            messages.warning(request, exc.message)
        return redirect("authentication:verify_email_notice")


class PasswordResetRequestView(FormView):
    template_name = "authentication/password_reset_request.html"
    form_class = PasswordResetRequestForm
    success_url = reverse_lazy("authentication:password_reset_sent")

    def form_valid(self, form):
        PasswordService.request_reset(form.cleaned_data["email"], self.request)
        return super().form_valid(form)


class PasswordResetSentView(TemplateView):
    template_name = "authentication/password_reset_sent.html"


class PasswordResetConfirmView(FormView):
    template_name = "authentication/password_reset_confirm.html"
    form_class = PasswordResetForm
    success_url = reverse_lazy("authentication:login")

    def form_valid(self, form):
        try:
            PasswordService.reset(self.kwargs["token"], form.cleaned_data["password"])
        except ZynoraError as exc:
            form.add_error(None, exc.message)
            return self.form_invalid(form)
        except Exception as exc:  # Django's own password validators
            form.add_error("password", str(exc))
            return self.form_invalid(form)

        messages.success(self.request, "Password updated. You can sign in now.")
        return super().form_valid(form)


class PasswordChangeView(LoginRequiredMixin, FormView):
    template_name = "authentication/password_change.html"
    form_class = PasswordChangeForm
    success_url = reverse_lazy("accounts:overview")

    def form_valid(self, form):
        try:
            PasswordService.change(
                self.request.user,
                form.cleaned_data["current_password"],
                form.cleaned_data["password"],
            )
        except ZynoraError as exc:
            form.add_error(None, exc.message)
            return self.form_invalid(form)
        except Exception as exc:
            form.add_error("password", str(exc))
            return self.form_invalid(form)

        # Keep the current session valid after a password change.
        from django.contrib.auth import update_session_auth_hash

        update_session_auth_hash(self.request, self.request.user)
        messages.success(self.request, "Your password was changed.")
        return super().form_valid(form)


class MFASetupView(LoginRequiredMixin, FormView):
    template_name = "authentication/mfa_setup.html"
    form_class = MFAEnrolForm
    success_url = reverse_lazy("authentication:mfa_recovery")

    def get(self, request, *args, **kwargs):
        enrolment = MFAService.begin_enrolment(request.user)
        request.session["mfa_enrolment_secret"] = enrolment["secret"]
        context = self.get_context_data(**enrolment)
        return self.render_to_response(context)

    def form_valid(self, form):
        try:
            codes = MFAService.confirm_enrolment(self.request.user, form.cleaned_data["code"])
        except ZynoraError as exc:
            form.add_error("code", exc.message)
            enrolment = {
                "secret": self.request.session.get("mfa_enrolment_secret", ""),
                "otpauth_url": "",
            }
            return self.render_to_response(self.get_context_data(form=form, **enrolment))

        self.request.session["mfa_recovery_codes"] = codes
        messages.success(self.request, "Two-factor authentication is on.")
        return super().form_valid(form)


class MFARecoveryCodesView(LoginRequiredMixin, TemplateView):
    template_name = "authentication/mfa_recovery.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Shown exactly once, then removed from the session.
        context["codes"] = self.request.session.pop("mfa_recovery_codes", [])
        return context


class MFADisableView(LoginRequiredMixin, View):
    def post(self, request):
        try:
            MFAService.disable(request.user, request.POST.get("password", ""))
            messages.info(request, "Two-factor authentication is off.")
        except ZynoraError as exc:
            messages.error(request, exc.message)
        return redirect("accounts:overview")


@login_required
def security_overview(request):
    """Small self-service security dashboard."""
    from apps.common.registry import services

    return render(request, "authentication/security_overview.html", {
        "attempts": services.authentication.recent_login_attempts(request.user.id, limit=15),
        "sessions": services.authentication.list_active_sessions(request.user.id),
        "mfa": services.authentication.mfa_status(request.user.id),
        "providers": services.authentication.linked_providers(request.user.id),
    })
