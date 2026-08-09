"""Serializers for the reports REST surface."""
from rest_framework import serializers

from .models import Report, ReportReason, SupportTicket


class ReportSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    reason = serializers.ChoiceField(choices=ReportReason.choices)
    description = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    context_type = serializers.CharField(required=False, allow_blank=True, max_length=40)
    context_id = serializers.UUIDField(required=False, allow_null=True)
    also_block = serializers.BooleanField(required=False, default=True)


class BlockSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    reason = serializers.CharField(required=False, allow_blank=True, max_length=200)


class ResolveReportSerializer(serializers.Serializer):
    report_id = serializers.UUIDField()
    outcome = serializers.ChoiceField(choices=Report.Outcome.choices)
    note = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class SupportTicketSerializer(serializers.Serializer):
    category = serializers.ChoiceField(choices=SupportTicket.Category.choices)
    subject = serializers.CharField(max_length=140)
    message = serializers.CharField(max_length=4000)
