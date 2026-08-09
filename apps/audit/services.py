"""Audit writing and querying."""
import logging

from .models import AuditCategory, AuditLog

logger = logging.getLogger(__name__)


class AuditService:
    @staticmethod
    def record(action, *, actor_id=None, actor_label="", category=AuditCategory.SYSTEM,
               description="", object_type="", object_id="", target_user_id=None,
               ip=None, user_agent="", metadata=None, sensitive=False):
        """Write one entry. Never raises — auditing must not break the action."""
        try:
            return AuditLog.objects.create(
                actor_id=actor_id,
                actor_label=actor_label[:191],
                action=action[:80],
                category=category,
                description=description[:400],
                object_type=object_type[:60],
                object_id=str(object_id)[:64] if object_id else "",
                target_user_id=target_user_id,
                ip_address=ip,
                user_agent=(user_agent or "")[:512],
                metadata=metadata or {},
                is_sensitive=sensitive,
            )
        except Exception:  # noqa: BLE001
            logger.exception("failed to write audit entry for %s", action)
            return None

    @staticmethod
    def for_user(user_id, limit=100):
        return AuditLog.objects.filter(actor_id=user_id)[:limit]

    @staticmethod
    def about_user(user_id, limit=100):
        return AuditLog.objects.filter(target_user_id=user_id)[:limit]

    @staticmethod
    def for_object(object_type, object_id, limit=50):
        return AuditLog.objects.filter(
            object_type=object_type, object_id=str(object_id)
        )[:limit]

    @staticmethod
    def search(*, category=None, action=None, actor_id=None,
               since=None, include_sensitive=False, limit=200):
        qs = AuditLog.objects.all()
        if category:
            qs = qs.filter(category=category)
        if action:
            qs = qs.filter(action__icontains=action)
        if actor_id:
            qs = qs.filter(actor_id=actor_id)
        if since:
            qs = qs.filter(created_at__gte=since)
        if not include_sensitive:
            qs = qs.filter(is_sensitive=False)
        return qs[:limit]

    @staticmethod
    def serialize(entry):
        return {
            "id": str(entry.id),
            "action": entry.action,
            "category": entry.category,
            "category_label": entry.get_category_display(),
            "description": entry.description,
            "actor_label": entry.actor_label or "system",
            "object_type": entry.object_type,
            "object_id": entry.object_id,
            "ip_address": entry.ip_address,
            "created_at": entry.created_at.isoformat(),
        }
