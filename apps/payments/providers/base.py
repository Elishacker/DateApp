"""Payment provider contract.

Every gateway implements the same four operations. Adding a provider means
adding one file and one registry entry — no other module changes.
"""
import hashlib
import hmac
import logging
from dataclasses import dataclass, field

from apps.common.exceptions import PaymentError

logger = logging.getLogger(__name__)


@dataclass
class ChargeResult:
    """What a provider returns when a charge is initiated."""

    success: bool
    provider_reference: str = ""
    checkout_url: str = ""
    #: True when the member must approve on their phone / on the gateway page.
    requires_action: bool = False
    message: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class WebhookResult:
    """Normalised view of a provider callback."""

    handled: bool
    event_type: str = ""
    provider_reference: str = ""
    payment_reference: str = ""
    status: str = ""
    amount: float = 0.0
    currency: str = ""
    fee: float = 0.0
    message: str = ""


class BaseProvider:
    code = ""
    label = ""
    #: Currencies the gateway settles in.
    currencies = ()
    #: True when the member must supply a mobile number rather than a card.
    requires_phone = False
    #: Human hint rendered on the checkout page.
    hint = ""

    def __init__(self, config=None):
        self.config = config or {}

    # ---- required operations ------------------------------------------------
    def charge(self, *, payment, return_url="", cancel_url=""):
        raise NotImplementedError

    def verify(self, provider_reference):
        """Server-side status poll — the source of truth over any callback."""
        raise NotImplementedError

    def refund(self, *, payment, amount, reason=""):
        raise NotImplementedError

    def parse_webhook(self, request_body, headers):
        raise NotImplementedError

    # ---- helpers ------------------------------------------------------------
    @property
    def is_configured(self):
        return all(self.config.get(key) for key in self.required_config)

    @property
    def required_config(self):
        return ()

    def ensure_configured(self):
        if not self.is_configured:
            raise PaymentError(
                f"{self.label} is not configured on this deployment.",
                code="provider_not_configured",
            )

    @staticmethod
    def verify_hmac(payload, signature, secret, algorithm="sha256"):
        """Constant-time signature check used by most gateways."""
        if not signature or not secret:
            return False
        digest = hmac.new(
            secret.encode(),
            payload if isinstance(payload, bytes) else payload.encode(),
            getattr(hashlib, algorithm),
        ).hexdigest()
        return hmac.compare_digest(digest, signature)

    def describe(self):
        return {
            "code": self.code,
            "label": self.label,
            "currencies": list(self.currencies),
            "requires_phone": self.requires_phone,
            "hint": self.hint,
            "is_configured": self.is_configured,
        }
