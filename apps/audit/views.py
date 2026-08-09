"""Audit browsing: personal activity log and the staff-wide trail."""
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from apps.common.constants import Capability
from apps.common.mixins import CapabilityRequiredMixin
from apps.common.registry import services

from .models import AuditCategory
from .services import AuditService


class MyActivityView(LoginRequiredMixin, TemplateView):
    """A member's own activity — a transparency feature, not an admin tool."""

    template_name = "audit/my_activity.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        entries = AuditService.for_user(str(self.request.user.id), limit=100)
        context["entries"] = [
            {
                "action": e.action,
                "description": e.description,
                "category_label": e.get_category_display(),
                "ip_address": e.ip_address,
                "created_at": e.created_at,
            }
            for e in entries if not e.is_sensitive
        ]
        context["has_entries"] = bool(context["entries"])
        return context


class AuditTrailView(CapabilityRequiredMixin, TemplateView):
    """Full trail with filters, staff only."""
    required_capability = Capability.VIEW_AUDIT_TRAIL

    template_name = "audit/trail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        category = self.request.GET.get("category") or None
        action = self.request.GET.get("action") or None

        entries = AuditService.search(
            category=category, action=action,
            include_sensitive=self.request.user.is_superuser, limit=300,
        )
        actor_ids = [str(e.actor_id) for e in entries if e.actor_id]
        refs = services.accounts.get_user_refs(actor_ids)

        context["entries"] = [
            {
                "id": str(e.id),
                "actor": refs.get(str(e.actor_id)) if e.actor_id else None,
                "actor_label": e.actor_label or "system",
                "action": e.action,
                "category_label": e.get_category_display(),
                "description": e.description,
                "object_type": e.object_type,
                "object_id": e.object_id,
                "ip_address": e.ip_address,
                "is_sensitive": e.is_sensitive,
                "created_at": e.created_at,
            }
            for e in entries
        ]
        context["has_entries"] = bool(context["entries"])
        context["categories"] = [
            {"value": value, "label": label, "is_active": value == category}
            for value, label in AuditCategory.choices
        ]
        context["active_category"] = category
        context["action_filter"] = action or ""
        return context
