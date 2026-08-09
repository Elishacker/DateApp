"""Social identity provider adapters.

Each adapter turns a provider access token into a normalised profile dict::

    {"provider", "uid", "email", "first_name", "last_name", "picture"}

Credentials come from the environment; a provider with no configured client id
raises rather than silently accepting unverified tokens.
"""
import json
import logging
import urllib.error
import urllib.request

from decouple import config

from apps.common.exceptions import ValidationError

logger = logging.getLogger("zynora.security")

PROVIDER_ENDPOINTS = {
    "google": "https://www.googleapis.com/oauth2/v3/userinfo",
    "facebook": "https://graph.facebook.com/me?fields=id,first_name,last_name,email,picture",
    "x": "https://api.twitter.com/2/users/me",
}


def _get_json(url, token):
    request = urllib.request.Request(url)
    request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        logger.warning("social token rejected: %s", exc)
        raise ValidationError("That sign-in could not be verified.") from exc
    except Exception as exc:  # noqa: BLE001
        logger.warning("social provider unreachable: %s", exc)
        raise ValidationError("The sign-in provider is unavailable right now.") from exc


def _google(token):
    data = _get_json(PROVIDER_ENDPOINTS["google"], token)
    if not data.get("email_verified"):
        raise ValidationError("Your Google email address is not verified.")
    return {
        "provider": "google",
        "uid": data["sub"],
        "email": data.get("email", ""),
        "first_name": data.get("given_name", ""),
        "last_name": data.get("family_name", ""),
        "picture": data.get("picture", ""),
    }


def _facebook(token):
    data = _get_json(PROVIDER_ENDPOINTS["facebook"], token)
    return {
        "provider": "facebook",
        "uid": data["id"],
        "email": data.get("email", ""),
        "first_name": data.get("first_name", ""),
        "last_name": data.get("last_name", ""),
        "picture": (data.get("picture") or {}).get("data", {}).get("url", ""),
    }


def _apple(token):
    """Apple returns an identity JWT; verification requires the Apple JWKS.

    Left explicit rather than half-implemented — wire in a JWKS check before
    enabling this provider in production.
    """
    raise ValidationError("Apple sign-in is not enabled on this deployment.")


ADAPTERS = {"google": _google, "facebook": _facebook, "apple": _apple}


def fetch_social_profile(provider, access_token):
    adapter = ADAPTERS.get(provider)
    if not adapter:
        raise ValidationError(f"'{provider}' sign-in is not supported.")
    if not config(f"{provider.upper()}_CLIENT_ID", default=""):
        raise ValidationError(f"{provider.title()} sign-in is not configured on this deployment.")

    profile = adapter(access_token)
    if not profile.get("email"):
        raise ValidationError(
            f"{provider.title()} did not share an email address. "
            "Use email registration instead."
        )
    return profile
