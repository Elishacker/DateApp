"""Reporting, blocking and support pages."""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import FormView, TemplateView, View

from apps.common.exceptions import ZynoraError
from apps.common.constants import Capability
from apps.common.mixins import CapabilityRequiredMixin
from apps.common.registry import services

from .forms import ReportForm, SupportTicketForm
from .models import Report
from .services import BlockService, ReportService, SupportService


class ReportUserView(LoginRequiredMixin, FormView):
    template_name = "reports/report.html"
    form_class = ReportForm
    success_url = reverse_lazy("discovery:feed")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["person"] = services.accounts.get_user_ref(str(self.kwargs["user_id"]))
        return context

    def form_valid(self, form):
        try:
            ReportService.create(
                self.request.user, self.kwargs["user_id"],
                reason=form.cleaned_data["reason"],
                description=form.cleaned_data.get("description", ""),
                evidence=form.cleaned_data.get("evidence"),
                also_block=form.cleaned_data.get("also_block", True),
            )
        except ZynoraError as exc:
            form.add_error(None, exc.message)
            return self.form_invalid(form)

        messages.success(
            self.request,
            "Thank you. Our safety team will review this and you won't see them again.",
        )
        return super().form_valid(form)


class BlockUserView(LoginRequiredMixin, View):
    def post(self, request, user_id):
        try:
            BlockService.block(request.user, user_id, request.POST.get("reason", ""))
        except ZynoraError as exc:
            return JsonResponse({"success": False, "message": exc.message},
                                status=exc.status_code)
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"success": True})
        messages.info(request, "Blocked. They can no longer see or contact you.")
        return redirect("discovery:feed")


class BlockListView(LoginRequiredMixin, TemplateView):
    template_name = "reports/blocked.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        blocks = BlockService.list_for(str(self.request.user.id))
        refs = services.accounts.get_user_refs([str(b.blocked_id) for b in blocks])

        context["rows"] = [
            {"user": refs.get(str(b.blocked_id)), "blocked_at": b.created_at,
             "reason": b.reason}
            for b in blocks if refs.get(str(b.blocked_id))
        ]
        context["has_rows"] = bool(context["rows"])
        context["empty_message"] = "You haven't blocked anyone."
        return context


class UnblockView(LoginRequiredMixin, View):
    def post(self, request, user_id):
        BlockService.unblock(request.user, user_id)
        messages.info(request, "Unblocked.")
        return redirect("reports:blocked")


class SupportView(LoginRequiredMixin, FormView):
    template_name = "reports/support.html"
    form_class = SupportTicketForm
    success_url = reverse_lazy("reports:support")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        tickets = SupportService.list_for(str(self.request.user.id))
        context["tickets"] = [
            {"number": t.number, "subject": t.subject, "status": t.status,
             "status_label": t.get_status_display(),
             "category_label": t.get_category_display(), "created_at": t.created_at}
            for t in tickets
        ]
        context["has_tickets"] = bool(context["tickets"])
        return context

    def form_valid(self, form):
        ticket = SupportService.create(self.request.user, **form.cleaned_data)
        messages.success(self.request, f"Ticket {ticket.number} created. We'll be in touch.")
        return super().form_valid(form)


class ReportQueueView(CapabilityRequiredMixin, TemplateView):
    """Safety team's review console."""
    required_capability = Capability.REVIEW_REPORTS

    template_name = "reports/queue.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        reports = ReportService.open_reports()
        subject_ids = [str(r.reported_id) for r in reports]
        reporter_ids = [str(r.reporter_id) for r in reports]
        refs = services.accounts.get_user_refs(subject_ids + reporter_ids)

        rows = []
        for report in reports:
            trust = services.moderation.get_trust_score(str(report.reported_id))
            rows.append({
                "report_id": str(report.id),
                "reported": refs.get(str(report.reported_id)),
                "reporter": refs.get(str(report.reporter_id)),
                "reason": report.reason,
                "reason_label": report.get_reason_display(),
                "description": report.description,
                "is_urgent": report.is_urgent,
                "created_at": report.created_at,
                "trust_score": trust["score"],
                "prior_reports": services.reports.count_reports_against(
                    str(report.reported_id)
                ),
            })

        context["rows"] = rows
        context["has_rows"] = bool(rows)
        context["stats"] = ReportService.stats()
        context["outcomes"] = [
            {"value": value, "label": label} for value, label in Report.Outcome.choices
        ]
        return context


class ResolveReportView(CapabilityRequiredMixin, View):
    required_capability = Capability.REVIEW_REPORTS

    def post(self, request, report_id):
        try:
            ReportService.resolve(
                report_id, request.POST.get("outcome", Report.Outcome.NONE),
                request.user, request.POST.get("note", ""),
            )
            messages.success(request, "Report resolved.")
        except ZynoraError as exc:
            messages.error(request, exc.message)
        return redirect("reports:queue")
