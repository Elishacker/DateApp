"""Service registry — the synchronous half of the service contract.

A module that needs data from another module never imports its models. It asks
the registry for the *interface*::

    from apps.common.registry import services

    profile = services.profiles.get_profile(user_id)

Because the lookup is indirect, extracting ``profiles`` into its own deployment
is a one-line change: register an HTTP-backed implementation under the same name
and every caller keeps compiling.
"""
import importlib
import logging

from django.conf import settings

logger = logging.getLogger("zynora.registry")


class ServiceNotAvailable(RuntimeError):
    """Raised when a module asks for a service that is not deployed."""


class ServiceRegistry:
    """Lazy, name-addressed access to every module's public interface."""

    #: Modules whose interfaces may be resolved locally (i.e. deployed in-process).
    LOCAL_MODULES = (
        "accounts", "authentication", "profiles", "onboarding", "discovery",
        "matching", "likes", "matches", "chat", "notifications", "subscriptions",
        "payments", "verification", "moderation", "reports", "analytics",
        "recommendation", "security", "audit",
    )

    def __init__(self):
        self._cache = {}
        self._overrides = {}

    def register(self, name, implementation):
        """Bind (or replace) a service implementation — used by tests and by
        remote clients once a module is extracted."""
        self._overrides[name] = implementation
        self._cache.pop(name, None)

    def unregister(self, name):
        self._overrides.pop(name, None)
        self._cache.pop(name, None)

    def resolve(self, name):
        if name in self._overrides:
            return self._overrides[name]
        if name in self._cache:
            return self._cache[name]

        remote = getattr(settings, "REMOTE_SERVICES", {}).get(name)
        if remote:
            from .remote import RemoteServiceClient

            client = RemoteServiceClient(name, remote)
            self._cache[name] = client
            return client

        if name not in self.LOCAL_MODULES:
            raise ServiceNotAvailable(f"Unknown service '{name}'.")

        try:
            module = importlib.import_module(f"apps.{name}.interface")
        except ModuleNotFoundError as exc:  # pragma: no cover - deployment error
            raise ServiceNotAvailable(f"Service '{name}' is not deployed: {exc}") from exc

        interface = getattr(module, "service", module)
        self._cache[name] = interface
        return interface

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self.resolve(name)

    def clear(self):
        self._cache.clear()


services = ServiceRegistry()
