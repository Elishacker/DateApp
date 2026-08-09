"""RFC 4648 / RFC 6238 TOTP, implemented on the standard library.

Deliberately dependency-free: MFA is a security control, and a security control
with a small, auditable surface beats one behind a third-party package. It is
compatible with Google Authenticator, Authy, 1Password and Aegis.
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

DIGITS = 6
PERIOD = 30
#: Accept the neighbouring step in each direction to tolerate clock drift.
DEFAULT_WINDOW = 1


def generate_secret(length=20):
    """Base32 secret (no padding) as expected by authenticator apps."""
    return base64.b32encode(secrets.token_bytes(length)).decode().rstrip("=")


def _hotp(secret, counter, digits=DIGITS):
    padding = "=" * (-len(secret) % 8)
    key = base64.b32decode(secret.upper() + padding, casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10 ** digits)).zfill(digits)


def current_counter(at=None):
    return int((at if at is not None else time.time()) // PERIOD)


def generate_code(secret, at=None):
    return _hotp(secret, current_counter(at))


def verify_code(secret, code, window=DEFAULT_WINDOW, last_counter=0):
    """Validate a code and return the counter it matched, else ``None``.

    Returning the counter lets the caller persist it and reject replays — the
    same code must not be usable twice inside its 30-second window.
    """
    code = (code or "").strip().replace(" ", "")
    if not code.isdigit() or len(code) != DIGITS:
        return None

    now = current_counter()
    for drift in range(-window, window + 1):
        counter = now + drift
        if counter <= last_counter:
            continue  # replay of an already-consumed step
        if hmac.compare_digest(_hotp(secret, counter), code):
            return counter
    return None


def provisioning_uri(secret, account_name, issuer="Zynora"):
    """otpauth:// URI to render as a QR code during enrolment."""
    label = quote(f"{issuer}:{account_name}")
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}"
        f"&algorithm=SHA1&digits={DIGITS}&period={PERIOD}"
    )


def generate_recovery_codes(count=10, groups=2, group_size=5):
    """Human-transcribable single-use codes, e.g. ``a1b2c-3d4e5``."""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    codes = []
    for _ in range(count):
        parts = [
            "".join(secrets.choice(alphabet) for _ in range(group_size))
            for _ in range(groups)
        ]
        codes.append("-".join(parts))
    return codes
