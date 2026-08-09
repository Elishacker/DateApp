"""Payments, invoices, refunds and webhook receipts.

``payments`` knows how to move money and nothing else. It never grants a
feature: on success it publishes ``PAYMENT_SUCCEEDED`` and the subscriptions
service decides what that entitles. That separation is what lets a payment
provider be added without touching the product.
"""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.constants import Currency
from apps.common.models import TimeStampedModel


class PaymentProvider(models.TextChoices):
    STRIPE = "stripe", "Stripe"
    PAYPAL = "paypal", "PayPal"
    FLUTTERWAVE = "flutterwave", "Flutterwave"
    PESAPAL = "pesapal", "Pesapal"
    MPESA = "mpesa", "M-Pesa"
    AIRTEL_MONEY = "airtel_money", "Airtel Money"
    TIGO_PESA = "tigo_pesa", "Mixx by Yas (Tigo Pesa)"
    HALOPESA = "halopesa", "HaloPesa"
    MANUAL = "manual", "Manual / offline"


class PaymentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"
    REFUNDED = "refunded", "Refunded"
    PARTIALLY_REFUNDED = "partially_refunded", "Partially refunded"


class PaymentPurpose(models.TextChoices):
    SUBSCRIPTION = "subscription", "New subscription"
    SUBSCRIPTION_RENEWAL = "subscription_renewal", "Subscription renewal"
    BOOST = "boost", "Profile boost"
    SUPER_LIKE_PACK = "super_like_pack", "Super like pack"
    OTHER = "other", "Other"


class Payment(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference = models.CharField(max_length=40, unique=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payments"
    )

    provider = models.CharField(max_length=20, choices=PaymentProvider.choices, db_index=True)
    status = models.CharField(
        max_length=20, choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING, db_index=True,
    )
    purpose = models.CharField(
        max_length=24, choices=PaymentPurpose.choices, default=PaymentPurpose.SUBSCRIPTION
    )

    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.TZS)
    fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    net_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount_refunded = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    provider_reference = models.CharField(max_length=191, blank=True, db_index=True)
    checkout_url = models.URLField(blank=True)
    payer_phone = models.CharField(max_length=20, blank=True)
    payer_email = models.EmailField(blank=True)

    #: What this pays for — a plan code, a subscription id, etc.
    metadata = models.JSONField(default=dict, blank=True)
    failure_reason = models.CharField(max_length=255, blank=True)

    initiated_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = "payments_payment"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["status", "provider"]),
        ]

    def __str__(self):
        return f"{self.reference} · {self.currency} {self.amount} ({self.status})"

    @property
    def is_settled(self):
        return self.status == PaymentStatus.SUCCEEDED

    @property
    def is_open(self):
        return self.status in {PaymentStatus.PENDING, PaymentStatus.PROCESSING}

    @property
    def amount_label(self):
        return f"{self.currency} {self.amount:,.2f}"

    @property
    def refundable_amount(self):
        return max(self.amount - self.amount_refunded, 0)

    def mark_succeeded(self, provider_reference="", fee=0):
        self.status = PaymentStatus.SUCCEEDED
        self.completed_at = timezone.now()
        self.provider_reference = provider_reference or self.provider_reference
        self.fee = fee or self.fee
        self.net_amount = self.amount - self.fee
        self.save(update_fields=["status", "completed_at", "provider_reference",
                                 "fee", "net_amount", "updated_at"])
        return self

    def mark_failed(self, reason=""):
        self.status = PaymentStatus.FAILED
        self.failure_reason = str(reason)[:255]
        self.save(update_fields=["status", "failure_reason", "updated_at"])
        return self


class Invoice(TimeStampedModel):
    """Issued once a payment settles. Immutable by design."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number = models.CharField(max_length=30, unique=True, db_index=True)
    payment = models.OneToOneField(Payment, on_delete=models.PROTECT, related_name="invoice")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="invoices"
    )

    description = models.CharField(max_length=200)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.TZS)

    billing_name = models.CharField(max_length=120, blank=True)
    billing_email = models.EmailField(blank=True)
    issued_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "payments_invoice"
        ordering = ["-issued_at"]

    def __str__(self):
        return self.number

    @property
    def total_label(self):
        return f"{self.currency} {self.total:,.2f}"


class Refund(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="refunds")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=255, blank=True)
    provider_reference = models.CharField(max_length=191, blank=True)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="refunds_issued",
    )
    is_complete = models.BooleanField(default=False)

    class Meta:
        db_table = "payments_refund"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Refund {self.amount} on {self.payment_id}"


class WebhookEvent(TimeStampedModel):
    """Raw provider callbacks, stored before processing.

    Persisting first means a provider retry is idempotent and a processing bug
    can be replayed rather than losing the notification.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.CharField(max_length=20, choices=PaymentProvider.choices, db_index=True)
    event_type = models.CharField(max_length=80, blank=True)
    external_id = models.CharField(max_length=191, blank=True, db_index=True)
    payload = models.JSONField(default=dict)
    headers = models.JSONField(default=dict, blank=True)

    signature_verified = models.BooleanField(default=False)
    is_processed = models.BooleanField(default=False, db_index=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    error = models.CharField(max_length=400, blank=True)

    class Meta:
        db_table = "payments_webhook_event"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["provider", "external_id"])]

    def __str__(self):
        return f"{self.provider}:{self.event_type}"


class SavedPaymentMethod(TimeStampedModel):
    """Tokenised method for auto-renewal. No PAN or CVV is ever stored."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="payment_methods"
    )
    provider = models.CharField(max_length=20, choices=PaymentProvider.choices)
    token = models.CharField(max_length=191)
    label = models.CharField(max_length=60, blank=True)
    last_four = models.CharField(max_length=4, blank=True)
    brand = models.CharField(max_length=30, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    expires_at = models.DateField(null=True, blank=True)
    is_default = models.BooleanField(default=False)

    class Meta:
        db_table = "payments_saved_method"
        ordering = ["-is_default", "-created_at"]

    def __str__(self):
        return self.label or f"{self.provider} ••••{self.last_four}"
