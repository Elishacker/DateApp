"""Onboarding wizard.

The view resolves which step to render and hands the template a fully prepared
context: a form, a title, a progress percentage and a list of step chips. The
template only outputs those values.
"""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.views.generic import TemplateView, View

from apps.common.exceptions import ZynoraError
from apps.common.registry import services

from .forms import IdentityStepForm, InterestsStepForm, LocationStepForm, PreferencesStepForm
from .models import OnboardingStep
from .services import OnboardingService


class WizardView(LoginRequiredMixin, TemplateView):
    """Renders the current step; POST submits it and advances."""

    def get_template_names(self):
        state = OnboardingService.state(self.request.user)
        return [f"onboarding/step_{state['step_key']}.html"]

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.has_completed_onboarding:
            return redirect("discovery:feed")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        state = OnboardingService.state(self.request.user)
        context.update(state)
        context.setdefault("form", self._build_form(state["step_number"]))
        context.update(self._step_extras(state["step_number"]))
        return context

    def post(self, request, *args, **kwargs):
        state = OnboardingService.state(request.user)
        step = state["step_number"]

        if step == OnboardingStep.WELCOME:
            OnboardingService._advance(request.user, OnboardingStep.WELCOME)
            return redirect("onboarding:wizard")

        if step == OnboardingStep.PHOTOS:
            try:
                OnboardingService.submit_photos(request.user)
            except ZynoraError as exc:
                messages.error(request, exc.message)
            return redirect("onboarding:wizard")

        form = self._build_form(step, data=request.POST)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))

        try:
            self._submit(step, request, form)
        except ZynoraError as exc:
            form.add_error(None, exc.message)
            return self.render_to_response(self.get_context_data(form=form))

        if OnboardingService.state(request.user)["is_complete"]:
            messages.success(request, "You're all set. Time to meet people.")
            return redirect("discovery:feed")
        return redirect("onboarding:wizard")

    # ---- helpers ------------------------------------------------------------
    def _build_form(self, step, data=None):
        if step == OnboardingStep.IDENTITY:
            return IdentityStepForm(data)
        if step == OnboardingStep.INTERESTS:
            return InterestsStepForm(data, interest_choices=self._interest_choices())
        if step == OnboardingStep.PREFERENCES:
            return PreferencesStepForm(data)
        if step == OnboardingStep.LOCATION:
            return LocationStepForm(data)
        return None

    def _submit(self, step, request, form):
        data = form.cleaned_data
        if step == OnboardingStep.IDENTITY:
            OnboardingService.submit_identity(request.user, **data)
        elif step == OnboardingStep.INTERESTS:
            OnboardingService.submit_interests(request.user, data["interests"])
        elif step == OnboardingStep.PREFERENCES:
            OnboardingService.submit_preferences(request.user, **data)
        elif step == OnboardingStep.LOCATION:
            OnboardingService.submit_location(request.user, **data)

    def _step_extras(self, step):
        """Extra render-ready data particular steps need."""
        if step == OnboardingStep.PHOTOS:
            profile = services.profiles.get_profile(str(self.request.user.id)) or {}
            return {
                "photos": services.profiles.get_photo_urls(
                    str(self.request.user.id), approved_only=False
                ),
                "photo_count": profile.get("photo_count", 0),
                "can_continue": profile.get("photo_count", 0) >= 1,
            }
        if step == OnboardingStep.INTERESTS:
            return {"interest_groups": self._grouped_interests()}
        return {}

    @staticmethod
    def _interest_choices():
        return [(i["id"], i["name"]) for i in services.profiles.list_interests()]

    @staticmethod
    def _grouped_interests():
        """Group the catalogue for the template — grouping is view work, not template work."""
        grouped = {}
        for interest in services.profiles.list_interests():
            grouped.setdefault(interest["category"], []).append(interest)
        return [
            {"category": category.replace("_", " ").title(), "items": items}
            for category, items in sorted(grouped.items())
        ]


class SkipStepView(LoginRequiredMixin, View):
    def post(self, request):
        state = OnboardingService.state(request.user)
        try:
            OnboardingService.skip_step(request.user, state["step_number"])
        except ZynoraError as exc:
            messages.warning(request, exc.message)
        if OnboardingService.state(request.user)["is_complete"]:
            return redirect("discovery:feed")
        return redirect("onboarding:wizard")


class BackStepView(LoginRequiredMixin, View):
    def post(self, request):
        progress = OnboardingService.get_progress(request.user)
        if progress.current_step > OnboardingStep.WELCOME:
            progress.current_step -= 1
            progress.save(update_fields=["current_step"])
        return redirect("onboarding:wizard")
