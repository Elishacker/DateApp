"""Payment pages and provider webhook endpoints."""
import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import TemplateView, View

from apps.common.exceptions import ZynoraError
from apps.common.registry import services

from .services import InvoiceService, PaymentService, WebhookService

logger = logging.getLogger(__name__)


class CheckoutView(LoginRequiredMixin, TemplateView):
    """Choose a payment method for an already-selected plan."""

    template_name = "payments/checkout.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        plan_code = self.request.GET.get("plan", "")
        plans = services.subscriptions.list_public_plans()
        plan = next((p for p in plans if p["code"] == plan_code), None)

        context["plan"] = plan
        context["providers"] = PaymentService.available_providers(
            plan["currency"] if plan else None
        )
        context["error"] = None if plan else "Choose a plan first."
        return context


class StartPaymentView(LoginRequiredMixin, View):
    def post(self, request):
        plan_code = request.POST.get("plan_code", "")
        provider = request.POST.get("provider", "")
        phone = request.POST.get("phone", "")
        coupon = request.POST.get("coupon_code", "")

        plans = services.subscriptions.list_public_plans()
        plan = next((p for p in plans if p["code"] == plan_code), None)
        if not plan:
            messages.error(request, "That plan is not available.")
            return redirect("subscriptions:plans")

        amount = plan["price"]
        if coupon:
            try:
                amount = services.subscriptions.quote_coupon(
                    coupon, str(request.user.id), plan_code
                )["new_amount"]
            except ZynoraError as exc:
                messages.warning(request, exc.message)
                coupon = ""

        try:
            result = PaymentService.create(
                request.user, amount=amount, currency=plan["currency"],
                provider_code=provider, purpose="subscription",
                metadata={"plan_code": plan_code, "coupon_code": coupon},
                phone=phone, request=request,
            )
        except ZynoraError as exc:
            messages.error(request, exc.message)
            return redirect("subscriptions:checkout", plan_code=plan_code)

        if result["checkout_url"]:
            return redirect(result["checkout_url"])

        messages.info(request, result["message"])
        return redirect("payments:pending", reference=result["reference"])


class PendingPaymentView(LoginRequiredMixin, TemplateView):
    """Waiting screen for mobile-money prompts; polls via static/js/payments.js."""

    template_name = "payments/pending.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        payment = PaymentService.get_by_reference(self.kwargs["reference"])
        context["payment"] = PaymentService.serialize(payment)
        context["poll_url"] = f"/payments/status/{payment.reference}/"
        return context


class PaymentStatusView(LoginRequiredMixin, View):
    """Polled by the pending page until the provider confirms."""

    def get(self, request, reference):
        payment = PaymentService.get_by_reference(reference)
        if str(payment.user_id) != str(request.user.id):
            return JsonResponse({"success": False}, status=403)

        if payment.is_open:
            PaymentService.poll_status(payment)
            payment.refresh_from_db()

        return JsonResponse({
            "success": True,
            "status": payment.status,
            "is_settled": payment.is_settled,
            "is_open": payment.is_open,
            "redirect_url": "/subscriptions/mine/" if payment.is_settled else "",
        })


class PaymentHistoryView(LoginRequiredMixin, TemplateView):
    template_name = "payments/history.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user_id = str(self.request.user.id)
        context["payments"] = PaymentService.history(user_id, limit=50)
        context["invoices"] = InvoiceService.list_for(user_id, limit=50)
        context["has_payments"] = bool(context["payments"])
        return context


class PaymentSuccessView(LoginRequiredMixin, TemplateView):
    template_name = "payments/success.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["summary"] = services.subscriptions.get_summary(str(self.request.user.id))
        return context


class PaymentCancelView(LoginRequiredMixin, TemplateView):
    template_name = "payments/cancelled.html"


@method_decorator(csrf_exempt, name="dispatch")
class WebhookView(View):
    """Provider callback sink: ``POST /payments/webhook/<provider>/``.

    CSRF-exempt by necessity; authenticity comes from the provider signature,
    which each adapter verifies in ``parse_webhook``.
    """

    def post(self, request, provider):
        event, handled = WebhookService.receive(
            provider, request.body, dict(request.headers)
        )
        # Always 200 on a *received* callback so providers stop retrying a
        # message we have already stored; failures are visible in the admin.
        return HttpResponse(
            "ok" if handled else "received",
            status=200,
            content_type="text/plain",
        )

    def get(self, request, provider):
        # Some gateways probe the URL before enabling it.
        return HttpResponse("ok", status=200, content_type="text/plain")
