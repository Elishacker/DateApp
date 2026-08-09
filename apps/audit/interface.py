"""Public contract of the audit service."""
from apps.common.interface import ModuleInterface

from .models import AuditCategory, AuditLog
from .services import AuditService


class AuditInterface(ModuleInterface):
    name = "audit"
    depends_on = ()

    def record(self, action, **kwargs):
        entry = AuditService.record(action, **kwargs)
        return str(entry.id) if entry else None

    def user_activity(self, user_id, limit=100):
        return [AuditService.serialize(e) for e in AuditService.for_user(user_id, limit)]

    def activity_about(self, user_id, limit=100):
        return [AuditService.serialize(e) for e in AuditService.about_user(user_id, limit)]

    def object_history(self, object_type, object_id, limit=50):
        return [
            AuditService.serialize(e)
            for e in AuditService.for_object(object_type, object_id, limit)
        ]

    def search(self, **filters):
        return [AuditService.serialize(e) for e in AuditService.search(**filters)]

    def categories(self):
        return [{"value": value, "label": label} for value, label in AuditCategory.choices]

    def stats(self, since=None):
        from django.db.models import Count

        qs = AuditLog.objects.all()
        if since:
            qs = qs.filter(created_at__gte=since)
        return {
            "total": qs.count(),
            "by_category": list(qs.values("category").annotate(count=Count("id"))),
        }


service = AuditInterface()
