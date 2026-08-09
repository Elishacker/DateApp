"""Reports REST endpoints."""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.common.mixins import ServiceResponseMixin
from apps.common.permissions import CanReviewReports
from apps.common.registry import services

from .models import Report
from .serializers import (
    BlockSerializer,
    ReportSerializer,
    ResolveReportSerializer,
    SupportTicketSerializer,
)
from .services import BlockService, ReportService, SupportService


class ReportAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        report = ReportService.create(
            request.user, data["user_id"], reason=data["reason"],
            description=data.get("description", ""),
            context_type=data.get("context_type", ""),
            context_id=data.get("context_id"),
            also_block=data.get("also_block", True),
        )
        return self.ok(
            {"report_id": str(report.id)},
            message="Report received. Our safety team will review it.",
            status=status.HTTP_201_CREATED,
        )


class BlockAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        blocks = BlockService.list_for(str(request.user.id))
        refs = services.accounts.get_user_refs([str(b.blocked_id) for b in blocks])
        return self.ok({
            "blocked": [
                {"user": refs.get(str(b.blocked_id)),
                 "blocked_at": b.created_at.isoformat(), "reason": b.reason}
                for b in blocks if refs.get(str(b.blocked_id))
            ],
        })

    def post(self, request):
        serializer = BlockSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        BlockService.block(
            request.user, serializer.validated_data["user_id"],
            serializer.validated_data.get("reason", ""),
        )
        return self.ok(message="Blocked.")

    def delete(self, request):
        serializer = BlockSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        BlockService.unblock(request.user, serializer.validated_data["user_id"])
        return self.ok(message="Unblocked.")


class SupportTicketAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tickets = SupportService.list_for(str(request.user.id))
        return self.ok({
            "tickets": [
                {"number": t.number, "subject": t.subject, "status": t.status,
                 "category": t.category, "created_at": t.created_at.isoformat()}
                for t in tickets
            ],
        })

    def post(self, request):
        serializer = SupportTicketSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ticket = SupportService.create(request.user, **serializer.validated_data)
        return self.ok({"number": ticket.number}, message="Ticket created.",
                       status=status.HTTP_201_CREATED)


class ReportQueueAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated, CanReviewReports]

    def get(self, request):
        reports = ReportService.open_reports()
        refs = services.accounts.get_user_refs(
            [str(r.reported_id) for r in reports] + [str(r.reporter_id) for r in reports]
        )
        return self.ok({
            "stats": ReportService.stats(),
            "reports": [
                {
                    "report_id": str(r.id),
                    "reported": refs.get(str(r.reported_id)),
                    "reporter": refs.get(str(r.reporter_id)),
                    "reason": r.reason, "description": r.description,
                    "is_urgent": r.is_urgent, "created_at": r.created_at.isoformat(),
                }
                for r in reports
            ],
        })

    def post(self, request):
        serializer = ResolveReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        ReportService.resolve(
            str(data["report_id"]), data["outcome"], request.user, data.get("note", "")
        )
        return self.ok(message="Report resolved.")
