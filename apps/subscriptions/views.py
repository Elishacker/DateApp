"""Subscription pages."""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import redirect
from django.views.generic import TemplateView, View

from apps.common.exceptions import ZynoraError
from apps.common.registry import services

from .services import CouponService, PlanService, SubscriptionService


class PlansView(LoginRequiredMixin, TemplateView):
    template_name = "subscriptions/plans.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user_id = str(self.request.user.id)
        summary = SubscriptionService.summary(user_id)

        # Mark the member's current plan here so the template needs no comparison.
        plans = PlanService.public_plans()
        for plan in plans:
            plan["is_current"] = plan["code"] == summary["plan_code"]
            plan["cta_label"] = "Your plan" if plan["is_current"] else (
                "Get started" if plan["is_free"] else f"Upgrade to {plan['name']}"
            )

        context["plans"] = plans
        context["summary"] = summary
        context["providers"] = services.payments.list_providers()
        return context


class MySubscriptionView(LoginRequiredMixin, TemplateView):
    template_name = "subscriptions/mine.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user_id = str(self.request.user.id)
        context["summary"] = SubscriptionService.summary(user_id)
        context["invoices"] = services.payments.list_payments(user_id, limit=10)
        return context


class CheckoutView(LoginRequiredMixin, TemplateView):
    """Plan chosen, payment method not yet selected."""

    template_name = "subscriptions/checkout.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        plan_code = self.kwargs["plan_code"]
        plan = next(
            (p for p in PlanService.public_plans() if p["code"] == plan_code), None
        )
        if not plan:
            context["error"] = "That plan is not available."
            return context

        context["plan"] = plan
        context["providers"] = services.payments.list_providers()
        context["amount_label"] = plan["price_label"]
        return context


class ApplyCouponView(LoginRequiredMixin, View):
    def post(self, request):
        try:
            quote = CouponService.quote(
                request.POST.get("code", ""), str(request.user.id),
                request.POST.get("plan_code", ""),
            )
        except ZynoraError as exc:
            return JsonResponse({"success": False, "message": exc.message}, status=400)
        return JsonResponse({"success": True, "quote": quote})


class CancelSubscriptionView(LoginRequiredMixin, View):
    def post(self, request):
        try:
            SubscriptionService.cancel(str(request.user.id), request.POST.get("reason", ""))
            messages.info(
                request,
                "Your plan is cancelled. You keep your features until the end of the term.",
            )
        except ZynoraError as exc:
            messages.error(request, exc.message)
        return redirect("subscriptions:mine")


class UseBoostView(LoginRequiredMixin, View):
    def post(self, request):
        from django.utils import timezone

        try:
            remaining = SubscriptionService.consume_boost(str(request.user.id))
        except ZynoraError as exc:
            return JsonResponse({"success": False, "message": exc.message},
                                status=exc.status_code)

        services.profiles.apply_boost(
            str(request.user.id), timezone.now() + timezone.timedelta(minutes=30)
        )
        return JsonResponse({
            "success": True,
            "remaining": remaining,
            "message": "You're boosted for the next 30 minutes.",
        })
