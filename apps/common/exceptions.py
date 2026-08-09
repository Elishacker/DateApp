"""Domain exceptions and the unified API error envelope."""
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


class ZynoraError(Exception):
    """Base class for expected, user-facing domain failures."""

    default_message = "Something went wrong."
    status_code = status.HTTP_400_BAD_REQUEST
    code = "error"

    def __init__(self, message=None, code=None, **context):
        self.message = message or self.default_message
        if code:
            self.code = code
        self.context = context
        super().__init__(self.message)


class ValidationError(ZynoraError):
    default_message = "The submitted data is invalid."
    code = "validation_error"


class PermissionDenied(ZynoraError):
    default_message = "You do not have permission to perform this action."
    status_code = status.HTTP_403_FORBIDDEN
    code = "permission_denied"


class NotFound(ZynoraError):
    default_message = "The requested resource does not exist."
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class QuotaExceeded(ZynoraError):
    """Raised when a free-tier limit is hit; the UI turns this into an upsell."""

    default_message = "You have reached your daily limit. Upgrade to continue."
    status_code = status.HTTP_402_PAYMENT_REQUIRED
    code = "quota_exceeded"


class SubscriptionRequired(ZynoraError):
    default_message = "This feature is available on a premium plan."
    status_code = status.HTTP_402_PAYMENT_REQUIRED
    code = "subscription_required"


class RateLimited(ZynoraError):
    default_message = "Too many requests. Please slow down."
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"


class ModerationBlocked(ZynoraError):
    default_message = "This content was blocked by our safety filters."
    status_code = status.HTTP_403_FORBIDDEN
    code = "moderation_blocked"


class PaymentError(ZynoraError):
    default_message = "The payment could not be processed."
    code = "payment_error"


def api_exception_handler(exc, context):
    """Render every error as ``{"success": false, "error": {...}}``."""
    if isinstance(exc, ZynoraError):
        return Response(
            {
                "success": False,
                "error": {"code": exc.code, "message": exc.message, "context": exc.context},
            },
            status=exc.status_code,
        )

    response = drf_exception_handler(exc, context)
    if response is not None:
        response.data = {
            "success": False,
            "error": {
                "code": getattr(exc, "default_code", "error"),
                "message": _first_message(response.data),
                "detail": response.data,
            },
        }
    return response


def _first_message(payload):
    if isinstance(payload, dict):
        for value in payload.values():
            return _first_message(value)
    if isinstance(payload, (list, tuple)) and payload:
        return _first_message(payload[0])
    return str(payload)
