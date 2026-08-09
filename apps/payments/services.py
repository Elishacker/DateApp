"""Payment orchestration, webhook processing and invoicing."""
import logging
import secrets
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.common.events import Event, publish
from apps.common.exceptions import NotFound, PaymentError, ValidationError
from apps.common.registry import services

from .models import (
    Invoice,
    Payment,
    PaymentStatus,
    Refund,
    SavedPaymentMethod,
    WebhookEvent,
)
from .providers import get_provider, list_providers

logger = logging.getLogger(__name__)

TAX_RATE = Decimal("0")  # set per jurisdiction; VAT is applied at invoice time


class PaymentService:
    @staticmethod
    def generate_reference():
        return f"ZYN-{timezone.now().strftime('%y%m%d')}-{secrets.token_hex(4).upper()}"

    @staticmethod
    @transaction.atomic
    def create(user, *, amount, currency, provider_code, purpose="subscription",
               metadata=None, phone="", request=None):
        """Create a payment record and ask the provider to start the charge."""
        amount = Decimal(str(amount))
        if amount <= 0:
            raise ValidationError("The payment amount must be greater than zero.")

        provider = get_provider(provider_code)
        if provider.currencies and currency not in provider.currencies:
            raise PaymentError(
                f"{provider.label} does not accept {currency}.",
                code="currency_not_supported",
            )
        if provider.requires_phone and not phone:
            raise ValidationError("Enter the mobile number to charge.", field="phone")

        from apps.common.utils import client_ip

        payment = Payment.objects.create(
            reference=PaymentService.generate_reference(),
            user=user,
            provider=provider_code,
            purpose=purpose,
            amount=amount,
            currency=currency,
            payer_phone=phone,
            payer_email=user.email,
            metadata=metadata or {},
            expires_at=timezone.now() + timezone.timedelta(hours=2),
            ip_address=client_ip(request) if request else None,
        )

        publish(Event.PAYMENT_INITIATED, {
            "payment_id": str(payment.id),
            "user_id": str(user.id),
            "reference": payment.reference,
            "amount": float(amount),
            "currency": currency,
            "provider": provider_code,
            "purpose": purpose,
        }, actor_id=user.id)

        try:
            result = provider.charge(payment=payment)
        except PaymentError:
            payment.mark_failed("Provider rejected the charge request.")
            raise

        payment.provider_reference = result.provider_reference
        payment.checkout_url = result.checkout_url
        payment.status = PaymentStatus.PROCESSING
        payment.save(update_fields=["provider_reference", "checkout_url",
                                    "status", "updated_at"])

        return {
            "payment_id": str(payment.id),
            "reference": payment.reference,
            "amount": float(payment.amount),
            "currency": payment.currency,
            "provider": provider_code,
            "checkout_url": result.checkout_url,
            "requires_action": result.requires_action,
            "message": result.message,
        }

    @staticmethod
    @transaction.atomic
    def settle(payment, *, provider_reference="", fee=0):
        """Mark a payment paid exactly once, then tell the platform."""
        if payment.status == PaymentStatus.SUCCEEDED:
            logger.info("payment %s already settled — ignoring", payment.reference)
            return payment

        payment.mark_succeeded(provider_reference, Decimal(str(fee or 0)))
        InvoiceService.issue(payment)

        publish(Event.PAYMENT_SUCCEEDED, {
            "payment_id": str(payment.id),
            "user_id": str(payment.user_id),
            "reference": payment.reference,
            "amount": float(payment.amount),
            "currency": payment.currency,
            "provider": payment.provider,
            "purpose": payment.purpose,
            "plan_code": payment.metadata.get("plan_code", ""),
            "coupon_code": payment.metadata.get("coupon_code", ""),
            "reference_id": payment.metadata.get("reference_id", ""),
        }, actor_id=payment.user_id)

        logger.info("payment %s settled", payment.reference)
        return payment

    @staticmethod
    def fail(payment, reason=""):
        if payment.status == PaymentStatus.SUCCEEDED:
            return payment
        payment.mark_failed(reason)
        publish(Event.PAYMENT_FAILED, {
            "payment_id": str(payment.id),
            "user_id": str(payment.user_id),
            "reference": payment.reference,
            "reason": reason,
            "provider": payment.provider,
        }, actor_id=payment.user_id)
        return payment

    @staticmethod
    def get_by_reference(reference):
        payment = Payment.objects.filter(reference=reference).first()
        if not payment:
            raise NotFound("Payment not found.")
        return payment

    @staticmethod
    def poll_status(payment):
        """Ask the provider directly — used when a callback never arrived."""
        if not payment.provider_reference:
            return payment.status
        provider = get_provider(payment.provider)
        result = provider.verify(payment.provider_reference)

        if result.status == "succeeded":
            PaymentService.settle(payment, provider_reference=payment.provider_reference,
                                  fee=result.fee)
        elif result.status == "failed":
            PaymentService.fail(payment, result.message or "Provider reported failure.")
        return payment.status

    @staticmethod
    def history(user_id, limit=20):
        rows = Payment.objects.filter(user_id=user_id)[:limit]
        return [PaymentService.serialize(p) for p in rows]

    @staticmethod
    def serialize(payment):
        return {
            "id": str(payment.id),
            "reference": payment.reference,
            "provider": payment.provider,
            "provider_label": payment.get_provider_display(),
            "status": payment.status,
            "status_label": payment.get_status_display(),
            "purpose": payment.purpose,
            "purpose_label": payment.get_purpose_display(),
            "amount": float(payment.amount),
            "amount_label": payment.amount_label,
            "currency": payment.currency,
            "checkout_url": payment.checkout_url,
            "created_at": payment.created_at.isoformat(),
            "completed_at": (
                payment.completed_at.isoformat() if payment.completed_at else None
            ),
            "is_settled": payment.is_settled,
            "is_open": payment.is_open,
        }

    @staticmethod
    def available_providers(currency=None):
        rows = list_providers()
        if currency:
            rows = [r for r in rows if not r["currencies"] or currency in r["currencies"]]
        return rows


class WebhookService:
    @staticmethod
    def receive(provider_code, request_body, headers):
        """Persist first, then process — so a retry is always idempotent."""
        event = WebhookEvent.objects.create(
            provider=provider_code,
            payload=WebhookService._safe_json(request_body),
            headers={k: v for k, v in headers.items() if k.lower() != "authorization"},
        )

        try:
            provider = get_provider(provider_code)
            result = provider.parse_webhook(request_body, headers)
        except Exception as exc:  # noqa: BLE001
            event.error = str(exc)[:400]
            event.save(update_fields=["error"])
            logger.exception("webhook parse failed for %s", provider_code)
            return event, False

        event.event_type = result.event_type[:80]
        event.external_id = result.provider_reference[:191]
        event.signature_verified = result.handled
        event.save(update_fields=["event_type", "external_id", "signature_verified"])

        if not result.handled:
            event.error = result.message[:400]
            event.save(update_fields=["error"])
            return event, False

        handled = WebhookService._apply(event, result)
        return event, handled

    @staticmethod
    @transaction.atomic
    def _apply(event, result):
        payment = None
        if result.payment_reference:
            payment = Payment.objects.filter(reference=result.payment_reference).first()
        if not payment and result.provider_reference:
            payment = Payment.objects.filter(
                provider_reference=result.provider_reference
            ).first()

        if not payment:
            event.error = "No matching payment for this callback."
            event.save(update_fields=["error"])
            logger.warning("orphan webhook %s for %s", event.id, event.provider)
            return False

        if result.status == "succeeded":
            PaymentService.settle(payment, provider_reference=result.provider_reference,
                                  fee=result.fee)
        elif result.status == "failed":
            PaymentService.fail(payment, result.message or "Payment declined.")
        elif result.status == "cancelled":
            payment.status = PaymentStatus.CANCELLED
            payment.save(update_fields=["status", "updated_at"])
        elif result.status == "refunded":
            RefundService.record_external(payment, result.amount)

        event.is_processed = True
        event.processed_at = timezone.now()
        event.save(update_fields=["is_processed", "processed_at"])
        return True

    @staticmethod
    def _safe_json(body):
        import json

        try:
            return json.loads(body or b"{}")
        except (ValueError, TypeError):
            return {"raw": str(body)[:2000]}


class InvoiceService:
    @staticmethod
    def issue(payment):
        if hasattr(payment, "invoice"):
            return payment.invoice

        subtotal = payment.amount
        tax_amount = (subtotal * TAX_RATE / 100).quantize(Decimal("0.01"))
        contact = services.accounts.get_contact_channels(str(payment.user_id)) or {}

        return Invoice.objects.create(
            number=InvoiceService.next_number(),
            payment=payment,
            user_id=payment.user_id,
            description=payment.get_purpose_display(),
            subtotal=subtotal,
            tax_rate=TAX_RATE,
            tax_amount=tax_amount,
            total=subtotal + tax_amount,
            currency=payment.currency,
            billing_name=contact.get("name", ""),
            billing_email=contact.get("email", ""),
        )

    @staticmethod
    def next_number():
        prefix = f"INV-{timezone.now().strftime('%Y%m')}"
        last = Invoice.objects.filter(number__startswith=prefix).order_by("-number").first()
        sequence = int(last.number.split("-")[-1]) + 1 if last else 1
        return f"{prefix}-{sequence:05d}"

    @staticmethod
    def list_for(user_id, limit=20):
        rows = Invoice.objects.filter(user_id=user_id)[:limit]
        return [
            {
                "number": i.number,
                "description": i.description,
                "total": float(i.total),
                "total_label": i.total_label,
                "currency": i.currency,
                "issued_at": i.issued_at.isoformat(),
                "payment_reference": i.payment.reference,
            }
            for i in rows
        ]


class RefundService:
    @staticmethod
    @transaction.atomic
    def issue(payment, amount, reason="", issued_by=None):
        amount = Decimal(str(amount))
        if amount <= 0 or amount > payment.refundable_amount:
            raise ValidationError("That refund amount is not valid.")
        if not payment.is_settled:
            raise ValidationError("Only settled payments can be refunded.")

        provider = get_provider(payment.provider)
        provider_reference = provider.refund(payment=payment, amount=amount, reason=reason)

        refund = Refund.objects.create(
            payment=payment, amount=amount, reason=reason,
            provider_reference=provider_reference or "",
            issued_by=issued_by, is_complete=True,
        )
        RefundService._apply_totals(payment, amount)

        publish(Event.REFUND_ISSUED, {
            "payment_id": str(payment.id),
            "user_id": str(payment.user_id),
            "amount": float(amount),
            "currency": payment.currency,
            "reason": reason,
        }, actor_id=getattr(issued_by, "id", None))
        return refund

    @staticmethod
    def record_external(payment, amount):
        """A refund initiated in the provider's own dashboard."""
        amount = Decimal(str(amount or payment.amount))
        Refund.objects.get_or_create(
            payment=payment, amount=amount,
            defaults={"reason": "Refunded at provider", "is_complete": True},
        )
        RefundService._apply_totals(payment, amount)

    @staticmethod
    def _apply_totals(payment, amount):
        payment.amount_refunded += amount
        payment.status = (
            PaymentStatus.REFUNDED if payment.amount_refunded >= payment.amount
            else PaymentStatus.PARTIALLY_REFUNDED
        )
        payment.save(update_fields=["amount_refunded", "status", "updated_at"])


class SavedMethodService:
    @staticmethod
    def save(user, *, provider, token, label="", last_four="", brand="", phone=""):
        if not SavedPaymentMethod.objects.filter(user=user).exists():
            is_default = True
        else:
            is_default = False
        return SavedPaymentMethod.objects.create(
            user=user, provider=provider, token=token, label=label,
            last_four=last_four, brand=brand, phone=phone, is_default=is_default,
        )

    @staticmethod
    def default_for(user_id):
        return SavedPaymentMethod.objects.filter(
            user_id=user_id, is_default=True
        ).first() or SavedPaymentMethod.objects.filter(user_id=user_id).first()

    @staticmethod
    def list_for(user_id):
        return [
            {
                "id": str(m.id), "provider": m.provider, "label": str(m),
                "last_four": m.last_four, "brand": m.brand,
                "is_default": m.is_default,
            }
            for m in SavedPaymentMethod.objects.filter(user_id=user_id)
        ]
