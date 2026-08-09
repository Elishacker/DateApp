"""Subscriptions' reactions to platform events."""
import logging

from apps.common.events import Event, subscribe

from .services import SubscriptionService

logger = logging.getLogger(__name__)


@subscribe(Event.PAYMENT_SUCCEEDED)
def grant_access_on_payment(envelope):
    """Payments proves money moved; subscriptions decides what it buys."""
    payload = envelope.payload
    purpose = payload.get("purpose")

    if purpose == "subscription" and payload.get("plan_code"):
        SubscriptionService.start(
            payload["user_id"], payload["plan_code"],
            payment_id=payload.get("payment_id"),
            coupon_code=payload.get("coupon_code", ""),
            amount_paid=payload.get("amount", 0),
            currency=payload.get("currency"),
        )
    elif purpose == "subscription_renewal" and payload.get("reference_id"):
        SubscriptionService.renew(payload["reference_id"], payload.get("payment_id"))
    elif purpose == "boost":
        logger.info("boost purchased by %s", payload.get("user_id"))


@subscribe(Event.SUBSCRIPTION_EXPIRED)
@subscribe(Event.SUBSCRIPTION_CANCELLED)
@subscribe(Event.SUBSCRIPTION_STARTED)
def refresh_entitlement_cache(envelope):
    user_id = envelope.payload.get("user_id")
    if user_id:
        SubscriptionService.invalidate(user_id)


@subscribe(Event.USER_DELETED)
def cancel_on_deletion(envelope):
    user_id = envelope.payload.get("user_id")
    if not user_id:
        return
    try:
        SubscriptionService.cancel(user_id, reason="account deleted")
    except Exception:  # noqa: BLE001 - no active subscription is fine
        pass
