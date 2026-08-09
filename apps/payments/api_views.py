"""Payments REST endpoints."""
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView

from apps.common.mixins import ServiceResponseMixin
from apps.common.permissions import IsAdministrator

from .serializers import CreatePaymentSerializer, RefundSerializer
from .services import InvoiceService, PaymentService, WebhookService


class ProviderListAPIView(ServiceResponseMixin, APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        currency = request.query_params.get("currency")
        return self.ok({"providers": PaymentService.available_providers(currency)})


class CreatePaymentAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = CreatePaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        result = PaymentService.create(
            request.user,
            amount=data["amount"], currency=data["currency"],
            provider_code=data["provider"], purpose=data.get("purpose", "subscription"),
            metadata=data.get("metadata", {}), phone=data.get("phone", ""),
            request=request,
        )
        return self.ok(result, message=result["message"])


class PaymentStatusAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, reference):
        payment = PaymentService.get_by_reference(reference)
        if str(payment.user_id) != str(request.user.id):
            return self.ok(message="Not found.", status=404)
        if payment.is_open:
            PaymentService.poll_status(payment)
            payment.refresh_from_db()
        return self.ok(PaymentService.serialize(payment))


class PaymentHistoryAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_id = str(request.user.id)
        return self.ok({
            "payments": PaymentService.history(user_id, limit=50),
            "invoices": InvoiceService.list_for(user_id, limit=50),
        })


class RefundAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated, IsAdministrator]

    def post(self, request):
        serializer = RefundSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment = PaymentService.get_by_reference(serializer.validated_data["reference"])

        from .services import RefundService

        refund = RefundService.issue(
            payment, serializer.validated_data["amount"],
            serializer.validated_data.get("reason", ""), request.user,
        )
        return self.ok({"refund_id": str(refund.id), "amount": float(refund.amount)},
                       message="Refund issued.")
