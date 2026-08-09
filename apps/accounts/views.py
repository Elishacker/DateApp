"""Server-rendered account settings pages."""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import FormView, TemplateView, View

from .forms import AccountDetailsForm, AccountSettingsForm
from .services import AccountService, DeviceService, SettingsService


class AccountOverviewView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/overview.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["devices"] = DeviceService.list_for(self.request.user)[:10]
        context["settings_row"] = SettingsService.get_or_create(self.request.user)
        return context


class AccountDetailsView(LoginRequiredMixin, FormView):
    template_name = "accounts/details.html"
    form_class = AccountDetailsForm
    success_url = reverse_lazy("accounts:details")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.request.user
        return kwargs

    def form_valid(self, form):
        form.save()
        messages.success(self.request, "Your details were updated.")
        return super().form_valid(form)


class AccountSettingsView(LoginRequiredMixin, FormView):
    template_name = "accounts/settings.html"
    form_class = AccountSettingsForm
    success_url = reverse_lazy("accounts:settings")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = SettingsService.get_or_create(self.request.user)
        return kwargs

    def form_valid(self, form):
        form.save()
        messages.success(self.request, "Preferences saved.")
        return super().form_valid(form)


class DeviceListView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/devices.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["devices"] = DeviceService.list_for(self.request.user)
        context["current_fingerprint"] = self.request.session.get("device_fingerprint")
        return context


class DeviceRevokeView(LoginRequiredMixin, View):
    def post(self, request, pk):
        DeviceService.revoke(request.user, pk)
        messages.success(request, "That device was signed out.")
        return redirect("accounts:devices")


class DeactivateView(LoginRequiredMixin, View):
    def post(self, request):
        AccountService.deactivate(request.user.id, request.POST.get("reason", ""))
        messages.info(request, "Your profile is hidden. Log back in any time to restore it.")
        return redirect("common:landing")
