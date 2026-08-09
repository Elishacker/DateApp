"""Reporting, blocking and support workflow."""
import logging
import secrets

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.common.events import Event, publish
from apps.common.exceptions import NotFound, ValidationError
from apps.common.registry import services
from apps.common.services import CacheService

from .models import Block, Report, ReportReason, SupportTicket

logger = logging.getLogger(__name__)
security_log = logging.getLogger("zynora.security")

#: Reports against one member within this window that trigger auto-suspension.
AUTO_SUSPEND_THRESHOLD = 5
BLOCK_CACHE_SECONDS = 300


class BlockService:
    @staticmethod
    @transaction.atomic
    def block(blocker, blocked_id, reason="", from_report=False):
        if str(blocker.id) == str(blocked_id):
            raise ValidationError("You cannot block yourself.")

        block, created = Block.objects.get_or_create(
            blocker=blocker, blocked_id=blocked_id,
            defaults={"reason": reason[:200], "from_report": from_report},
        )
        if created:
            BlockService._invalidate(str(blocker.id), str(blocked_id))
            publish(Event.USER_BLOCKED, {
                "blocker_id": str(blocker.id),
                "blocked_id": str(blocked_id),
                "reason": reason,
            }, actor_id=blocker.id)
        return block

    @staticmethod
    def unblock(blocker, blocked_id):
        deleted, _ = Block.objects.filter(blocker=blocker, blocked_id=blocked_id).delete()
        BlockService._invalidate(str(blocker.id), str(blocked_id))
        return bool(deleted)

    @staticmethod
    def is_blocked_between(user_a, user_b):
        """Symmetric check — a block hides both directions.

        Cached because discovery and chat hit this on every render.
        """
        key = tuple(sorted([str(user_a), str(user_b)]))
        cached = CacheService.get("reports", "block", *key)
        if cached is not None:
            return bool(cached)

        exists = Block.objects.filter(
            Q(blocker_id=key[0], blocked_id=key[1])
            | Q(blocker_id=key[1], blocked_id=key[0])
        ).exists()
        CacheService.set("reports", "block", *key, value=int(exists), ttl=BLOCK_CACHE_SECONDS)
        return exists

    @staticmethod
    def blocked_ids(user_id):
        """Everyone invisible to this member, in either direction."""
        made = Block.objects.filter(blocker_id=user_id).values_list("blocked_id", flat=True)
        received = Block.objects.filter(blocked_id=user_id).values_list("blocker_id", flat=True)
        return [str(pk) for pk in {*made, *received}]

    @staticmethod
    def list_for(user_id):
        return Block.objects.filter(blocker_id=user_id).order_by("-created_at")

    @staticmethod
    def _invalidate(user_a, user_b):
        key = tuple(sorted([user_a, user_b]))
        CacheService.delete("reports", "block", *key)


class ReportService:
    @staticmethod
    @transaction.atomic
    def create(reporter, reported_id, *, reason, description="",
               evidence=None, context_type="", context_id=None, also_block=True):
        if str(reporter.id) == str(reported_id):
            raise ValidationError("You cannot report yourself.")
        if not services.accounts.exists(reported_id):
            raise NotFound("That member does not exist.")

        recent = Report.objects.filter(
            reporter=reporter, reported_id=reported_id,
            created_at__gte=timezone.now() - timezone.timedelta(days=1),
        ).exists()
        if recent:
            raise ValidationError("You have already reported this person today.")

        report = Report.objects.create(
            reporter=reporter, reported_id=reported_id, reason=reason,
            description=description[:2000], evidence=evidence,
            context_type=context_type, context_id=context_id,
        )

        if also_block:
            BlockService.block(reporter, reported_id, reason="reported", from_report=True)

        # Feed the safety signals: trust score and the moderation queue.
        services.moderation.penalise(str(reported_id), ReportService._penalty(reason),
                                     reason=f"reported for {reason}")
        if context_type and context_id:
            services.moderation.flag_content(
                owner_id=str(reported_id), object_type=context_type,
                object_id=str(context_id), reason=f"user report: {reason}",
                severity="high" if report.is_urgent else "medium",
                snapshot=description[:500],
            )

        publish(Event.USER_REPORTED, {
            "report_id": str(report.id),
            "reporter_id": str(reporter.id),
            "reported_id": str(reported_id),
            "reason": reason,
            "is_urgent": report.is_urgent,
        }, actor_id=reporter.id)

        ReportService._check_threshold(reported_id)
        logger.info("report %s filed against %s", report.id, reported_id)
        return report

    @staticmethod
    def _penalty(reason):
        return {
            ReportReason.UNDERAGE: 60,
            ReportReason.THREAT: 50,
            ReportReason.HATE_SPEECH: 40,
            ReportReason.SCAM: 35,
            ReportReason.FAKE_PROFILE: 25,
            ReportReason.HARASSMENT: 25,
            ReportReason.INAPPROPRIATE_PHOTOS: 20,
        }.get(reason, 10)

    @staticmethod
    def _check_threshold(reported_id):
        """Repeated recent reports suspend the account pending human review."""
        window = timezone.now() - timezone.timedelta(days=7)
        count = Report.objects.filter(
            reported_id=reported_id, created_at__gte=window
        ).values("reporter_id").distinct().count()

        if count >= AUTO_SUSPEND_THRESHOLD:
            security_log.warning(
                "auto-suspending %s after %d distinct reports", reported_id, count
            )
            services.accounts.suspend(
                str(reported_id),
                reason=f"Automatically suspended after {count} reports",
                permanent=False,
            )

    @staticmethod
    def open_reports(urgent_first=True, limit=100):
        qs = Report.objects.filter(status__in=[Report.Status.OPEN, Report.Status.REVIEWING])
        if urgent_first:
            qs = qs.order_by("-is_urgent", "created_at")
        return qs[:limit]

    @staticmethod
    def get(report_id):
        report = Report.objects.filter(id=report_id).first()
        if not report:
            raise NotFound("Report not found.")
        return report

    @staticmethod
    @transaction.atomic
    def resolve(report_id, outcome, moderator, note=""):
        report = ReportService.get(report_id)
        report.resolve(outcome, moderator, note)

        reported_id = str(report.reported_id)
        if outcome == Report.Outcome.SHADOW_BANNED:
            services.moderation.set_shadow_ban(reported_id, True)
        elif outcome == Report.Outcome.SUSPENDED:
            services.accounts.suspend(reported_id, reason=note or "Policy violation",
                                      permanent=False, actor_id=str(moderator.id))
        elif outcome == Report.Outcome.BANNED:
            services.accounts.suspend(reported_id, reason=note or "Policy violation",
                                      permanent=True, actor_id=str(moderator.id))
        elif outcome == Report.Outcome.NONE:
            # A dismissed report should not leave the accused penalised.
            services.moderation.reward(reported_id, points=5)

        return report

    @staticmethod
    def stats():
        return {
            "open": Report.objects.filter(status=Report.Status.OPEN).count(),
            "urgent": Report.objects.filter(
                status=Report.Status.OPEN, is_urgent=True
            ).count(),
            "actioned": Report.objects.filter(status=Report.Status.ACTIONED).count(),
            "dismissed": Report.objects.filter(status=Report.Status.DISMISSED).count(),
        }


class SupportService:
    @staticmethod
    def create(user, *, category, subject, message):
        ticket = SupportTicket.objects.create(
            number=SupportService.next_number(),
            user=user, category=category,
            subject=subject[:140], message=message[:4000],
            is_priority=services.subscriptions.has_entitlement(
                str(user.id), "priority_support"
            ),
        )
        return ticket

    @staticmethod
    def next_number():
        return f"TKT-{timezone.now():%y%m}-{secrets.token_hex(3).upper()}"

    @staticmethod
    def list_for(user_id):
        return SupportTicket.objects.filter(user_id=user_id)
