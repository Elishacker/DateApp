"""Stripe adapter (Checkout Sessions).

Uses the REST API over the standard library so the project has no hard
dependency on the ``stripe`` package. Swap ``_request`` for the official SDK if
you prefer — nothing outside this file changes.
"""
import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from apps.common.exceptions import PaymentError

from .base import BaseProvider, ChargeResult, WebhookResult

logger = logging.getLogger(__name__)

API_BASE = "https://api.stripe.com/v1"
#: Currencies Stripe treats as zero-decimal (amount is not multiplied by 100).
ZERO_DECIMAL = {"BIF", "CLP", "DJF", "GNF", "JPY", "KMF", "KRW", "MGA",
                "PYG", "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF"}


class StripeProvider(BaseProvider):
    code = "stripe"
    label = "Card (Stripe)"
    currencies = ("USD", "EUR", "KES", "UGX")
    hint = "Pay securely with Visa, Mastercard or Amex."

    @property
    def required_config(self):
        return ("secret_key",)

    # ---- operations ---------------------------------------------------------
    def charge(self, *, payment, return_url="", cancel_url=""):
        self.ensure_configured()
        amount = self._to_minor_units(payment.amount, payment.currency)

        data = {
            "mode": "payment",
            "success_url": return_url or "https://zynora.app/payments/success/",
            "cancel_url": cancel_url or "https://zynora.app/payments/cancel/",
            "client_reference_id": payment.reference,
            "line_items[0][quantity]": "1",
            "line_items[0][price_data][currency]": payment.currency.lower(),
            "line_items[0][price_data][unit_amount]": str(amount),
            "line_items[0][price_data][product_data][name]": self._describe(payment),
            "metadata[payment_reference]": payment.reference,
            "metadata[user_id]": str(payment.user_id),
        }
        if payment.payer_email:
            data["customer_email"] = payment.payer_email

        response = self._request("POST", "/checkout/sessions", data)
        return ChargeResult(
            success=True,
            provider_reference=response.get("id", ""),
            checkout_url=response.get("url", ""),
            requires_action=True,
            message="Complete your payment on the Stripe checkout page.",
            raw=response,
        )

    def verify(self, provider_reference):
        self.ensure_configured()
        session = self._request("GET", f"/checkout/sessions/{provider_reference}")
        paid = session.get("payment_status") == "paid"
        return WebhookResult(
            handled=True,
            event_type="checkout.session.verified",
            provider_reference=provider_reference,
            payment_reference=session.get("client_reference_id", ""),
            status="succeeded" if paid else "pending",
            amount=self._from_minor_units(
                session.get("amount_total", 0), session.get("currency", "").upper()
            ),
            currency=session.get("currency", "").upper(),
        )

    def refund(self, *, payment, amount, reason=""):
        self.ensure_configured()
        session = self._request("GET", f"/checkout/sessions/{payment.provider_reference}")
        intent = session.get("payment_intent")
        if not intent:
            raise PaymentError("This payment cannot be refunded automatically.")

        response = self._request("POST", "/refunds", {
            "payment_intent": intent,
            "amount": str(self._to_minor_units(amount, payment.currency)),
            "reason": "requested_by_customer",
            "metadata[note]": reason[:200],
        })
        return response.get("id", "")

    def parse_webhook(self, request_body, headers):
        secret = self.config.get("webhook_secret", "")
        signature = headers.get("Stripe-Signature", "")

        # Stripe signs "t=<ts>,v1=<sig>"; extract v1 before comparing.
        v1 = ""
        for part in signature.split(","):
            if part.strip().startswith("v1="):
                v1 = part.strip()[3:]
                break

        verified = True
        if secret:
            timestamp = next(
                (p.strip()[2:] for p in signature.split(",") if p.strip().startswith("t=")), ""
            )
            signed_payload = f"{timestamp}.".encode() + (
                request_body if isinstance(request_body, bytes) else request_body.encode()
            )
            verified = self.verify_hmac(signed_payload, v1, secret)
            if not verified:
                logger.warning("stripe webhook signature mismatch")
                return WebhookResult(handled=False, message="Invalid signature.")

        payload = json.loads(request_body or b"{}")
        event_type = payload.get("type", "")
        obj = payload.get("data", {}).get("object", {})

        status_map = {
            "checkout.session.completed": "succeeded",
            "checkout.session.async_payment_succeeded": "succeeded",
            "checkout.session.async_payment_failed": "failed",
            "checkout.session.expired": "cancelled",
            "charge.refunded": "refunded",
        }
        if event_type not in status_map:
            return WebhookResult(handled=False, event_type=event_type,
                                 message="Event ignored.")

        currency = (obj.get("currency") or "").upper()
        return WebhookResult(
            handled=True,
            event_type=event_type,
            provider_reference=obj.get("id", ""),
            payment_reference=(
                obj.get("client_reference_id")
                or obj.get("metadata", {}).get("payment_reference", "")
            ),
            status=status_map[event_type],
            amount=self._from_minor_units(obj.get("amount_total", 0), currency),
            currency=currency,
        )

    # ---- internals ----------------------------------------------------------
    @staticmethod
    def _to_minor_units(amount, currency):
        if currency.upper() in ZERO_DECIMAL:
            return int(round(float(amount)))
        return int(round(float(amount) * 100))

    @staticmethod
    def _from_minor_units(amount, currency):
        if currency.upper() in ZERO_DECIMAL:
            return float(amount or 0)
        return float(amount or 0) / 100

    @staticmethod
    def _describe(payment):
        return {
            "subscription": "Zynora subscription",
            "subscription_renewal": "Zynora subscription renewal",
            "boost": "Zynora profile boost",
            "super_like_pack": "Zynora super like pack",
        }.get(payment.purpose, "Zynora purchase")

    def _request(self, method, path, data=None):
        url = f"{API_BASE}{path}"
        body = urllib.parse.urlencode(data).encode() if data else None
        request = urllib.request.Request(url, data=body, method=method)
        request.add_header("Authorization", f"Bearer {self.config['secret_key']}")
        request.add_header("Content-Type", "application/x-www-form-urlencoded")

        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            logger.error("stripe %s %s failed: %s", method, path, detail)
            raise PaymentError("The card payment could not be started.") from exc
        except Exception as exc:  # noqa: BLE001
            logger.error("stripe unreachable: %s", exc)
            raise PaymentError("The payment provider is unavailable.") from exc
