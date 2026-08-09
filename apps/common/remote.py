"""HTTP transport for extracted services.

When a module leaves the monolith you add it to ``REMOTE_SERVICES``::

    REMOTE_SERVICES = {"chat": {"base_url": "http://chat.internal:8000", "token": "..."}}

The registry then hands callers a :class:`RemoteServiceClient` instead of the
local ``interface`` module. Method calls become POSTs to
``<base_url>/internal/<method>/`` with a JSON body, so call sites are unchanged.
"""
import json
import logging
import urllib.error
import urllib.request

from .exceptions import ZynoraError

logger = logging.getLogger("zynora.registry")


class RemoteServiceError(ZynoraError):
    default_message = "A dependent service is unavailable."
    code = "service_unavailable"
    status_code = 503


class RemoteServiceClient:
    """Thin RPC shim. Deliberately dependency-free (stdlib only)."""

    def __init__(self, name, config):
        self.name = name
        self.base_url = config["base_url"].rstrip("/")
        self.token = config.get("token", "")
        self.timeout = config.get("timeout", 5)

    def __getattr__(self, method):
        if method.startswith("_"):
            raise AttributeError(method)

        def _call(*args, **kwargs):
            # Positional args are forwarded in order and re-applied by the
            # remote dispatcher, so local and remote call sites stay identical.
            return self._post(method, {"args": list(args), "kwargs": kwargs})

        _call.__name__ = method
        return _call

    def _post(self, method, payload):
        url = f"{self.base_url}/internal/{self.name}/{method}/"
        body = json.dumps(payload, default=str).encode()
        request = urllib.request.Request(url, data=body, method="POST")
        request.add_header("Content-Type", "application/json")
        request.add_header("X-Service-Caller", "zynora-core")
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                envelope = json.loads(response.read() or b"null") or {}
                if not envelope.get("success"):
                    error = envelope.get("error", {})
                    raise RemoteServiceError(
                        error.get("message", "Remote call failed."),
                        code=error.get("code", "service_error"),
                    )
                # Unwrap so callers see exactly what the local interface returns.
                return envelope.get("result")
        except urllib.error.HTTPError as exc:
            logger.error("Remote service %s.%s failed: %s", self.name, method, exc)
            raise RemoteServiceError(f"{self.name}.{method} returned {exc.code}") from exc
        except RemoteServiceError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("Remote service %s.%s unreachable: %s", self.name, method, exc)
            raise RemoteServiceError(f"{self.name} is unreachable") from exc
