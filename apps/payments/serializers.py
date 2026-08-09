"""Serializers for the payments REST surface."""
from rest_framework import serializers

from .models import Invoice, Payment, PaymentProvider, PaymentPurpose


class CreatePaymentSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=1)
    currency = serializers.CharField(max_length=3)
    provider = serializers.ChoiceField(choices=PaymentProvider.choices)
    purpose = serializers.ChoiceField(
        choices=PaymentPurpose.choices, default=PaymentPurpose.SUBSCRIPTION
    )
    phone = serializers.CharField(required=False, allow_blank=True, max_length=20)
    metadata = serializers.DictField(required=False, default=dict)

    def validate_currency(self, value):
        return value.upper()


class PaymentSerializer(serializers.ModelSerializer):
    amount_label = serializers.CharField(read_only=True)
    is_settled = serializers.BooleanField(read_only=True)

    class Meta:
        model = Payment
        fields = ["id", "reference", "provider", "status", "purpose", "amount",
                  "amount_label", "currency", "checkout_url", "created_at",
                  "completed_at", "is_settled"]
        read_only_fields = fields


class InvoiceSerializer(serializers.ModelSerializer):
    total_label = serializers.CharField(read_only=True)

    class Meta:
        model = Invoice
        fields = ["number", "description", "subtotal", "tax_rate", "tax_amount",
                  "total", "total_label", "currency", "issued_at"]
        read_only_fields = fields


class RefundSerializer(serializers.Serializer):
    reference = serializers.CharField(max_length=40)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=1)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=255)
