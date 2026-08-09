"""Public contract of the payments service."""
from apps.common.interface import ModuleInterface

from .models import Payment, PaymentStatus
from .services import (
    InvoiceService,
    PaymentService,
    RefundService,
    SavedMethodService,
)


class PaymentsInterface(ModuleInterface):
    name = "payments"
    depends_on = ("accounts",)

    def create_payment(self, *, user_id, amount, currency, provider,
                       purpose="subscription", metadata=None, phone=""):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.filter(id=user_id).first()
        if not user:
            return None
        return PaymentService.create(
            user, amount=amount, currency=currency, provider_code=provider,
            purpose=purpose, metadata=metadata, phone=phone,
        )

    def charge_saved_method(self, *, user_id, amount, currency,
                            purpose="subscription_renewal", reference_id=""):
        """Used by subscription auto-renewal."""
        method = SavedMethodService.default_for(user_id)
        if not method:
            return None
        return self.create_payment(
            user_id=user_id, amount=amount, currency=currency,
            provider=method.provider, purpose=purpose,
            metadata={"reference_id": reference_id, "saved_method": str(method.id)},
            phone=method.phone,
        )

    def get_payment(self, payment_id):
        payment = Payment.objects.filter(id=payment_id).first()
        return PaymentService.serialize(payment) if payment else None

    def get_payment_by_reference(self, reference):
        payment = Payment.objects.filter(reference=reference).first()
        return PaymentService.serialize(payment) if payment else None

    def list_payments(self, user_id, limit=20):
        return PaymentService.history(user_id, limit)

    def list_invoices(self, user_id, limit=20):
        return InvoiceService.list_for(user_id, limit)

    def list_providers(self, currency=None):
        return PaymentService.available_providers(currency)

    def list_saved_methods(self, user_id):
        return SavedMethodService.list_for(user_id)

    def refresh_status(self, payment_id):
        payment = Payment.objects.filter(id=payment_id).first()
        if not payment:
            return None
        return PaymentService.poll_status(payment)

    def issue_refund(self, payment_id, amount, reason="", actor_id=None):
        from django.contrib.auth import get_user_model

        payment = Payment.objects.filter(id=payment_id).first()
        if not payment:
            return None
        actor = get_user_model().objects.filter(id=actor_id).first() if actor_id else None
        refund = RefundService.issue(payment, amount, reason, actor)
        return {"refund_id": str(refund.id), "amount": float(refund.amount)}

    def revenue_stats(self, since=None):
        from django.db.models import Count, Sum

        qs = Payment.objects.filter(status=PaymentStatus.SUCCEEDED)
        if since:
            qs = qs.filter(completed_at__gte=since)
        aggregate = qs.aggregate(gross=Sum("amount"), fees=Sum("fee"), count=Count("id"))
        return {
            "gross": float(aggregate["gross"] or 0),
            "fees": float(aggregate["fees"] or 0),
            "net": float((aggregate["gross"] or 0) - (aggregate["fees"] or 0)),
            "transactions": aggregate["count"] or 0,
            "by_provider": list(
                qs.values("provider").annotate(total=Sum("amount"), count=Count("id"))
            ),
        }


service = PaymentsInterface()
