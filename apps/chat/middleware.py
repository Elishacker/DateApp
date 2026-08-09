"""WebSocket authentication.

Browsers cannot set headers on a WebSocket handshake, so the token arrives in
the query string. Session cookies are still honoured for the server-rendered UI,
which is why both stacks are chained.
"""
import logging
from urllib.parse import parse_qs

from channels.auth import AuthMiddlewareStack
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser

logger = logging.getLogger("zynora.security")


@database_sync_to_async
def _user_from_token(raw_token):
    from django.contrib.auth import get_user_model
    from rest_framework_simplejwt.exceptions import TokenError
    from rest_framework_simplejwt.tokens import AccessToken

    try:
        token = AccessToken(raw_token)
        user = get_user_model().objects.filter(id=token["user_id"]).first()
    except (TokenError, KeyError) as exc:
        logger.info("websocket token rejected: %s", exc)
        return AnonymousUser()

    if not user or not user.is_active or user.is_banned:
        return AnonymousUser()
    return user


class JWTAuthMiddleware:
    """Resolves ``?token=<jwt>`` into ``scope['user']``."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        query = parse_qs(scope.get("query_string", b"").decode())
        token = (query.get("token") or [None])[0]

        # Runs *inside* AuthMiddlewareStack, after session auth has already
        # resolved scope["user"] through Channels' own lazy-user machinery.
        # Setting scope["user"] here unconditionally (via setdefault) before
        # that machinery runs — as this used to — plants a plain AnonymousUser
        # in the slot Channels expects to swap a UserLazyObject into, so its
        # resolved (session-authenticated) user is silently discarded.
        if token and not getattr(scope.get("user"), "is_authenticated", False):
            scope["user"] = await _user_from_token(token)
        return await self.inner(scope, receive, send)


def JWTAuthMiddlewareStack(inner):  # noqa: N802 - matches Channels' naming
    """Session auth first, JWT as a fallback for native clients."""
    return AuthMiddlewareStack(JWTAuthMiddleware(inner))
