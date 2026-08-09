"""Provider registry.

``get_provider("mpesa")`` returns a configured adapter. Credentials come from
the environment, so an unconfigured provider shows in the UI as disabled rather
than failing at checkout.
"""
from decouple import config

from apps.common.exceptions import PaymentError

from .base import BaseProvider, ChargeResult, WebhookResult
from .mobile_money import (
    AirtelMoneyProvider,
    FlutterwaveProvider,
    HaloPesaProvider,
    MpesaProvider,
    PayPalProvider,
    PesapalProvider,
    TigoPesaProvider,
)
from .stripe import StripeProvider

PROVIDER_CLASSES = {
    StripeProvider.code: StripeProvider,
    PayPalProvider.code: PayPalProvider,
    FlutterwaveProvider.code: FlutterwaveProvider,
    PesapalProvider.code: PesapalProvider,
    MpesaProvider.code: MpesaProvider,
    AirtelMoneyProvider.code: AirtelMoneyProvider,
    TigoPesaProvider.code: TigoPesaProvider,
    HaloPesaProvider.code: HaloPesaProvider,
}

#: Environment variable suffixes read for each provider,
#: e.g. MPESA_CONSUMER_KEY, STRIPE_SECRET_KEY, FLUTTERWAVE_API_KEY.
CONFIG_KEYS = (
    "base_url", "api_key", "secret_key", "public_key", "client_id", "client_secret",
    "consumer_key", "consumer_secret", "shortcode", "passkey", "webhook_secret",
    "callback_url", "redirect_url", "notification_id", "country",
)


def _load_config(code):
    prefix = code.upper()
    return {key: config(f"{prefix}_{key.upper()}", default="") for key in CONFIG_KEYS}


def get_provider(code):
    provider_class = PROVIDER_CLASSES.get(code)
    if not provider_class:
        raise PaymentError(f"'{code}' is not a supported payment method.",
                           code="unknown_provider")
    return provider_class(_load_config(code))


def list_providers(configured_only=False):
    """Render-ready provider list for the checkout page."""
    rows = []
    for code, provider_class in PROVIDER_CLASSES.items():
        provider = provider_class(_load_config(code))
        if configured_only and not provider.is_configured:
            continue
        rows.append(provider.describe())
    return rows


__all__ = [
    "BaseProvider", "ChargeResult", "WebhookResult",
    "get_provider", "list_providers", "PROVIDER_CLASSES",
]
