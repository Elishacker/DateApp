"""East African mobile money adapters.

M-Pesa, Airtel Money, Mixx by Yas (Tigo Pesa) and HaloPesa all follow the same
shape: push an STK / USSD prompt to the payer's handset, then wait for an
asynchronous callback. They share :class:`MobileMoneyProvider` and differ only
in endpoint, credentials and payload keys.

Aggregators (Flutterwave, Pesapal) are also here because from Zynora's side they
behave identically: redirect or prompt, then call us back.
"""
import base64
import json
import logging
import urllib.error
import urllib.request
from datetime import datetime

from apps.common.exceptions import PaymentError

from .base import BaseProvider, ChargeResult, WebhookResult

logger = logging.getLogger(__name__)


class MobileMoneyProvider(BaseProvider):
    """Shared STK-push behaviour."""

    requires_phone = True
    hint = "You'll get a prompt on your phone — enter your PIN to approve."

    #: Endpoint used to start a collection.
    charge_path = ""
    #: Endpoint used to poll a transaction.
    status_path = ""

    @property
    def required_config(self):
        return ("base_url", "api_key")

    def charge(self, *, payment, return_url="", cancel_url=""):
        self.ensure_configured()
        if not payment.payer_phone:
            raise PaymentError("A mobile number is required for this payment method.",
                               code="phone_required")

        response = self._post(self.charge_path, self.build_charge_payload(payment))
        reference = self.extract_reference(response)
        if not reference:
            raise PaymentError(
                response.get("message", "The payment prompt could not be sent."),
            )
        return ChargeResult(
            success=True,
            provider_reference=reference,
            requires_action=True,
            message=f"Check {payment.payer_phone} and approve the payment.",
            raw=response,
        )

    def verify(self, provider_reference):
        self.ensure_configured()
        response = self._get(f"{self.status_path}/{provider_reference}")
        return WebhookResult(
            handled=True,
            event_type="status.poll",
            provider_reference=provider_reference,
            status=self.map_status(response),
            amount=float(response.get("amount", 0) or 0),
            currency=response.get("currency", ""),
        )

    def refund(self, *, payment, amount, reason=""):
        # Mobile money reversals are usually manual/operator-initiated.
        raise PaymentError(
            f"{self.label} refunds are processed manually. Raise a support ticket.",
            code="manual_refund_required",
        )

    def parse_webhook(self, request_body, headers):
        secret = self.config.get("webhook_secret", "")
        signature = headers.get("X-Signature", "") or headers.get("Verif-Hash", "")

        if secret and not (
            signature == secret or self.verify_hmac(request_body, signature, secret)
        ):
            logger.warning("%s webhook signature mismatch", self.code)
            return WebhookResult(handled=False, message="Invalid signature.")

        payload = json.loads(request_body or b"{}")
        return self.build_webhook_result(payload)

    # ---- per-provider hooks -------------------------------------------------
    def build_charge_payload(self, payment):
        return {
            "amount": float(payment.amount),
            "currency": payment.currency,
            "phone_number": payment.payer_phone,
            "external_reference": payment.reference,
            "narration": "Zynora subscription",
            "callback_url": self.config.get("callback_url", ""),
        }

    def extract_reference(self, response):
        return (
            response.get("transaction_id")
            or response.get("reference")
            or response.get("CheckoutRequestID")
            or response.get("id", "")
        )

    def map_status(self, payload):
        raw = str(
            payload.get("status")
            or payload.get("ResultCode")
            or payload.get("transaction_status", "")
        ).lower()
        if raw in {"0", "success", "successful", "completed", "complete"}:
            return "succeeded"
        if raw in {"pending", "processing", "1032"}:
            return "processing"
        if raw in {"cancelled", "canceled"}:
            return "cancelled"
        return "failed"

    def build_webhook_result(self, payload):
        return WebhookResult(
            handled=True,
            event_type=payload.get("event", "collection.update"),
            provider_reference=self.extract_reference(payload),
            payment_reference=(
                payload.get("external_reference") or payload.get("AccountReference", "")
            ),
            status=self.map_status(payload),
            amount=float(payload.get("amount", 0) or 0),
            currency=payload.get("currency", ""),
        )

    # ---- transport ----------------------------------------------------------
    def _headers(self):
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.get('api_key', '')}",
        }

    def _post(self, path, payload):
        return self._request("POST", path, payload)

    def _get(self, path):
        return self._request("GET", path)

    def _request(self, method, path, payload=None):
        url = f"{self.config['base_url'].rstrip('/')}/{path.lstrip('/')}"
        body = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(url, data=body, method=method)
        for key, value in self._headers().items():
            request.add_header(key, value)

        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            logger.error("%s %s %s failed: %s", self.code, method, path, detail)
            raise PaymentError(f"{self.label} rejected the request.") from exc
        except Exception as exc:  # noqa: BLE001
            logger.error("%s unreachable: %s", self.code, exc)
            raise PaymentError(f"{self.label} is unavailable right now.") from exc


class MpesaProvider(MobileMoneyProvider):
    code = "mpesa"
    label = "M-Pesa"
    currencies = ("TZS", "KES")
    charge_path = "/mpesa/stkpush/v1/processrequest"
    status_path = "/mpesa/stkpushquery/v1/query"

    @property
    def required_config(self):
        return ("base_url", "consumer_key", "consumer_secret", "shortcode", "passkey")

    def build_charge_payload(self, payment):
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        shortcode = self.config["shortcode"]
        password = base64.b64encode(
            f"{shortcode}{self.config['passkey']}{timestamp}".encode()
        ).decode()
        return {
            "BusinessShortCode": shortcode,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": int(float(payment.amount)),
            "PartyA": payment.payer_phone.lstrip("+"),
            "PartyB": shortcode,
            "PhoneNumber": payment.payer_phone.lstrip("+"),
            "CallBackURL": self.config.get("callback_url", ""),
            "AccountReference": payment.reference,
            "TransactionDesc": "Zynora subscription",
        }

    def _headers(self):
        """Daraja uses OAuth client-credentials rather than a static key."""
        token = self._access_token()
        return {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}

    def _access_token(self):
        credentials = base64.b64encode(
            f"{self.config['consumer_key']}:{self.config['consumer_secret']}".encode()
        ).decode()
        url = (f"{self.config['base_url'].rstrip('/')}"
               "/oauth/v1/generate?grant_type=client_credentials")
        request = urllib.request.Request(url)
        request.add_header("Authorization", f"Basic {credentials}")
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.loads(response.read()).get("access_token", "")
        except Exception as exc:  # noqa: BLE001
            logger.error("mpesa token request failed: %s", exc)
            raise PaymentError("M-Pesa is unavailable right now.") from exc

    def build_webhook_result(self, payload):
        callback = payload.get("Body", {}).get("stkCallback", payload)
        items = {
            item.get("Name"): item.get("Value")
            for item in callback.get("CallbackMetadata", {}).get("Item", [])
        }
        return WebhookResult(
            handled=True,
            event_type="stk.callback",
            provider_reference=callback.get("CheckoutRequestID", ""),
            payment_reference=items.get("AccountReference", ""),
            status="succeeded" if str(callback.get("ResultCode")) == "0" else "failed",
            amount=float(items.get("Amount", 0) or 0),
            currency="TZS",
            message=callback.get("ResultDesc", ""),
        )


class AirtelMoneyProvider(MobileMoneyProvider):
    code = "airtel_money"
    label = "Airtel Money"
    currencies = ("TZS", "KES", "UGX")
    charge_path = "/merchant/v1/payments/"
    status_path = "/standard/v1/payments"

    def build_charge_payload(self, payment):
        return {
            "reference": payment.reference,
            "subscriber": {
                "country": self.config.get("country", "TZ"),
                "currency": payment.currency,
                "msisdn": payment.payer_phone.lstrip("+"),
            },
            "transaction": {
                "amount": float(payment.amount),
                "country": self.config.get("country", "TZ"),
                "currency": payment.currency,
                "id": payment.reference,
            },
        }


class TigoPesaProvider(MobileMoneyProvider):
    code = "tigo_pesa"
    label = "Mixx by Yas (Tigo Pesa)"
    currencies = ("TZS",)
    charge_path = "/collection/v1/charge"
    status_path = "/collection/v1/status"


class HaloPesaProvider(MobileMoneyProvider):
    code = "halopesa"
    label = "HaloPesa"
    currencies = ("TZS",)
    charge_path = "/collection/charge"
    status_path = "/collection/status"


class FlutterwaveProvider(MobileMoneyProvider):
    """Aggregator: hosted checkout page covering cards and mobile money."""

    code = "flutterwave"
    label = "Flutterwave"
    currencies = ("TZS", "KES", "UGX", "USD")
    requires_phone = False
    hint = "Cards, bank transfer and mobile money in one place."
    charge_path = "/payments"
    status_path = "/transactions"

    def build_charge_payload(self, payment):
        return {
            "tx_ref": payment.reference,
            "amount": str(payment.amount),
            "currency": payment.currency,
            "redirect_url": self.config.get("redirect_url", ""),
            "customer": {
                "email": payment.payer_email or "member@zynora.app",
                "phonenumber": payment.payer_phone,
            },
            "customizations": {"title": "Zynora", "description": "Zynora subscription"},
        }

    def charge(self, *, payment, return_url="", cancel_url=""):
        self.ensure_configured()
        response = self._post(self.charge_path, self.build_charge_payload(payment))
        link = (response.get("data") or {}).get("link", "")
        if not link:
            raise PaymentError(response.get("message", "Checkout could not be created."))
        return ChargeResult(
            success=True,
            provider_reference=payment.reference,
            checkout_url=link,
            requires_action=True,
            message="Complete your payment on the Flutterwave page.",
            raw=response,
        )

    def build_webhook_result(self, payload):
        data = payload.get("data", payload)
        status = str(data.get("status", "")).lower()
        return WebhookResult(
            handled=True,
            event_type=payload.get("event", "charge.completed"),
            provider_reference=str(data.get("id", "")),
            payment_reference=data.get("tx_ref", ""),
            status="succeeded" if status == "successful" else (
                "failed" if status == "failed" else "processing"
            ),
            amount=float(data.get("amount", 0) or 0),
            currency=data.get("currency", ""),
            fee=float(data.get("app_fee", 0) or 0),
        )


class PesapalProvider(MobileMoneyProvider):
    """Aggregator widely used across Tanzania, Kenya and Uganda."""

    code = "pesapal"
    label = "Pesapal"
    currencies = ("TZS", "KES", "UGX", "USD")
    requires_phone = False
    hint = "Cards and mobile money via Pesapal."
    charge_path = "/api/Transactions/SubmitOrderRequest"
    status_path = "/api/Transactions/GetTransactionStatus"

    def build_charge_payload(self, payment):
        return {
            "id": payment.reference,
            "currency": payment.currency,
            "amount": float(payment.amount),
            "description": "Zynora subscription",
            "callback_url": self.config.get("callback_url", ""),
            "notification_id": self.config.get("notification_id", ""),
            "billing_address": {
                "email_address": payment.payer_email or "member@zynora.app",
                "phone_number": payment.payer_phone,
            },
        }

    def charge(self, *, payment, return_url="", cancel_url=""):
        self.ensure_configured()
        response = self._post(self.charge_path, self.build_charge_payload(payment))
        url = response.get("redirect_url", "")
        if not url:
            raise PaymentError(response.get("message", "Checkout could not be created."))
        return ChargeResult(
            success=True,
            provider_reference=response.get("order_tracking_id", payment.reference),
            checkout_url=url,
            requires_action=True,
            message="Complete your payment on the Pesapal page.",
            raw=response,
        )


class PayPalProvider(BaseProvider):
    code = "paypal"
    label = "PayPal"
    currencies = ("USD", "EUR")
    hint = "Pay with your PayPal balance or a linked card."

    @property
    def required_config(self):
        return ("client_id", "client_secret")

    def charge(self, *, payment, return_url="", cancel_url=""):
        self.ensure_configured()
        # Order creation intentionally delegated to the PayPal JS SDK on the
        # client; the server only verifies and captures via webhook.
        return ChargeResult(
            success=True,
            provider_reference=payment.reference,
            requires_action=True,
            message="Approve the payment in the PayPal window.",
        )

    def verify(self, provider_reference):
        return WebhookResult(handled=False, provider_reference=provider_reference,
                             status="pending")

    def refund(self, *, payment, amount, reason=""):
        raise PaymentError("PayPal refunds are issued from the PayPal dashboard.",
                           code="manual_refund_required")

    def parse_webhook(self, request_body, headers):
        payload = json.loads(request_body or b"{}")
        event_type = payload.get("event_type", "")
        resource = payload.get("resource", {})
        status_map = {
            "PAYMENT.CAPTURE.COMPLETED": "succeeded",
            "PAYMENT.CAPTURE.DENIED": "failed",
            "PAYMENT.CAPTURE.REFUNDED": "refunded",
        }
        if event_type not in status_map:
            return WebhookResult(handled=False, event_type=event_type)
        amount = resource.get("amount", {})
        return WebhookResult(
            handled=True,
            event_type=event_type,
            provider_reference=resource.get("id", ""),
            payment_reference=resource.get("custom_id", ""),
            status=status_map[event_type],
            amount=float(amount.get("value", 0) or 0),
            currency=amount.get("currency_code", ""),
        )
