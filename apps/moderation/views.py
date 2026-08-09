"""Moderator review console."""
from django.contrib import messages
from django.shortcuts import redirect
from django.views.generic import TemplateView, View

from apps.common.constants import Capability
from apps.common.mixins import CapabilityRequiredMixin
from apps.common.registry import services

from .models import ModerationCase
from .services import ModerationService

QUEUE_TABS = (
    ("all", "All", None),
    ("photos", "Photos", ModerationCase.ObjectType.PROFILE_PHOTO),
    ("verification", "Verification", ModerationCase.ObjectType.VERIFICATION_PHOTO),
    ("messages", "Messages", ModerationCase.ObjectType.MESSAGE),
    ("profiles", "Profile text", ModerationCase.ObjectType.PROFILE_TEXT),
)


class QueueView(CapabilityRequiredMixin, TemplateView):
    required_capability = Capability.MODERATE_CONTENT

    template_name = "moderation/queue.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        active = self.request.GET.get("tab", "all")
        object_type = next((t for key, _, t in QUEUE_TABS if key == active), None)

        cases = ModerationService.pending_cases(object_type, limit=100)
        owner_ids = [str(c.owner_id) for c in cases]
        refs = services.accounts.get_user_refs(owner_ids)

        rows = []
        for case in cases:
            trust = services.moderation.get_trust_score(str(case.owner_id))
            rows.append({
                "case_id": str(case.id),
                "owner": refs.get(str(case.owner_id)),
                "object_type": case.object_type,
                "object_type_label": case.get_object_type_display(),
                "content_url": case.content_url,
                "content_snapshot": case.content_snapshot[:300],
                "risk_score": case.risk_score,
                "severity": case.severity,
                "reasons": case.reasons,
                "trust_score": trust["score"],
                "trust_band": trust["band"],
                "created_at": case.created_at,
            })

        context["rows"] = rows
        context["has_rows"] = bool(rows)
        context["stats"] = ModerationService.queue_stats()
        context["tabs"] = [
            {"key": key, "label": label, "is_active": key == active}
            for key, label, _ in QUEUE_TABS
        ]
        context["empty_message"] = "The queue is clear. Nice work."
        return context


class DecideView(CapabilityRequiredMixin, View):
    required_capability = Capability.MODERATE_CONTENT

    def post(self, request, case_id):
        approved = request.POST.get("decision") == "approve"
        note = request.POST.get("note", "")
        case = ModerationService.get(case_id)
        ModerationService.decide(case, approved, request.user, note)
        messages.success(request, "Approved." if approved else "Rejected.")
        return redirect(request.META.get("HTTP_REFERER", "moderation:queue"))


class TrustListView(CapabilityRequiredMixin, TemplateView):
    required_capability = Capability.MODERATE_CONTENT

    template_name = "moderation/trust.html"

    def get_context_data(self, **kwargs):
        from .models import TrustScore

        context = super().get_context_data(**kwargs)
        scores = TrustScore.objects.order_by("score")[:100]
        refs = services.accounts.get_user_refs([str(s.user_id) for s in scores])

        context["rows"] = [
            {
                "user": refs.get(str(s.user_id)),
                "score": s.score,
                "band": s.band,
                "reports_received": s.reports_received,
                "content_rejected": s.content_rejected,
                "is_shadow_banned": s.is_shadow_banned,
            }
            for s in scores if refs.get(str(s.user_id))
        ]
        return context


class ShadowBanView(CapabilityRequiredMixin, View):
    required_capability = Capability.SHADOW_BAN

    def post(self, request, user_id):
        banned = request.POST.get("banned") == "true"
        services.moderation.set_shadow_ban(str(user_id), banned)
        messages.info(request, "Shadow ban applied." if banned else "Shadow ban lifted.")
        return redirect("moderation:trust")
