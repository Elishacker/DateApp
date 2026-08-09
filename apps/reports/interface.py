"""Public contract of the reports service.

``is_blocked_between`` is on the hot path for discovery, chat and matching, so
it is cached and kept dependency-free.
"""
from apps.common.interface import ModuleInterface

from .models import Block, Report
from .services import BlockService, ReportService, SupportService


class ReportsInterface(ModuleInterface):
    name = "reports"
    depends_on = ("accounts", "moderation", "subscriptions")

    # ---- blocks (hot path) --------------------------------------------------
    def is_blocked_between(self, user_a, user_b):
        return BlockService.is_blocked_between(user_a, user_b)

    def get_blocked_user_ids(self, user_id):
        return BlockService.blocked_ids(user_id)

    def block_user(self, blocker_id, blocked_id, reason=""):
        from django.contrib.auth import get_user_model

        blocker = get_user_model().objects.filter(id=blocker_id).first()
        if not blocker:
            return None
        block = BlockService.block(blocker, blocked_id, reason)
        return {"id": str(block.id), "blocked_id": str(block.blocked_id)}

    def unblock_user(self, blocker_id, blocked_id):
        from django.contrib.auth import get_user_model

        blocker = get_user_model().objects.filter(id=blocker_id).first()
        return BlockService.unblock(blocker, blocked_id) if blocker else False

    def count_blocks(self, user_id):
        return Block.objects.filter(blocker_id=user_id).count()

    # ---- reports ------------------------------------------------------------
    def create_report(self, reporter_id, reported_id, *, reason, description="",
                      context_type="", context_id=None, also_block=True):
        from django.contrib.auth import get_user_model

        reporter = get_user_model().objects.filter(id=reporter_id).first()
        if not reporter:
            return None
        report = ReportService.create(
            reporter, reported_id, reason=reason, description=description,
            context_type=context_type, context_id=context_id, also_block=also_block,
        )
        return {"id": str(report.id), "is_urgent": report.is_urgent}

    def count_reports_against(self, user_id, days=None):
        qs = Report.objects.filter(reported_id=user_id)
        if days:
            from django.utils import timezone

            qs = qs.filter(created_at__gte=timezone.now() - timezone.timedelta(days=days))
        return qs.count()

    def has_reported(self, reporter_id, reported_id):
        return Report.objects.filter(
            reporter_id=reporter_id, reported_id=reported_id
        ).exists()

    def open_report_count(self):
        return Report.objects.filter(status=Report.Status.OPEN).count()

    def stats(self):
        return ReportService.stats()

    # ---- support ------------------------------------------------------------
    def open_ticket(self, user_id, *, category, subject, message):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.filter(id=user_id).first()
        if not user:
            return None
        ticket = SupportService.create(
            user, category=category, subject=subject, message=message
        )
        return {"number": ticket.number, "status": ticket.status}


service = ReportsInterface()
