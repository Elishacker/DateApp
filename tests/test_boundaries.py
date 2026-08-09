"""The architecture tests.

These are the tests that keep Zynora's microservice-readiness honest. If one of
them fails, a module has reached into another module's internals and the
extraction story is broken.
"""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.common.registry import ServiceRegistry, services


class BoundaryTests(TestCase):
    def test_no_module_imports_another_modules_internals(self):
        """``check_boundaries`` must pass with zero violations."""
        out = StringIO()
        try:
            call_command("check_boundaries", stdout=out, stderr=out)
        except SystemExit:
            self.fail(f"Service boundary violations detected:\n{out.getvalue()}")
        self.assertIn("boundaries clean", out.getvalue())

    def test_every_module_exposes_an_interface(self):
        for name in ServiceRegistry.LOCAL_MODULES:
            with self.subTest(module=name):
                interface = services.resolve(name)
                self.assertTrue(hasattr(interface, "describe"),
                                f"{name} has no ModuleInterface contract")
                description = interface.describe()
                self.assertEqual(description["name"], name)
                self.assertTrue(description["methods"],
                                f"{name} exposes no public methods")

    def test_declared_dependencies_are_real_modules(self):
        known = set(ServiceRegistry.LOCAL_MODULES)
        for name in ServiceRegistry.LOCAL_MODULES:
            description = services.resolve(name).describe()
            for dependency in description["depends_on"]:
                with self.subTest(module=name, dependency=dependency):
                    self.assertIn(dependency, known,
                                  f"{name} declares unknown dependency '{dependency}'")

    def test_leaf_services_depend_on_nothing(self):
        """These must stay callable even when everything else is down."""
        for name in ("accounts", "subscriptions", "moderation", "audit"):
            with self.subTest(module=name):
                self.assertEqual(services.resolve(name).describe()["depends_on"], [],
                                 f"{name} must remain a leaf service")

    def test_registry_can_be_overridden(self):
        """Extraction relies on swapping an implementation at the registry."""

        class FakeAccounts:
            name = "accounts"
            depends_on = ()

            def describe(self):
                return {"name": "accounts", "depends_on": [], "methods": ["get_user_ref"]}

            def get_user_ref(self, user_id):
                return {"id": str(user_id), "display_name": "Stub"}

        services.register("accounts", FakeAccounts())
        try:
            self.assertEqual(services.accounts.get_user_ref("abc")["display_name"], "Stub")
        finally:
            services.unregister("accounts")

        # Original implementation must come back after unregistering.
        self.assertEqual(services.accounts.describe()["name"], "accounts")


class EventBusTests(TestCase):
    def test_publish_never_raises_when_a_handler_fails(self):
        from apps.common.events import publish, subscribe, unsubscribe

        def exploding_handler(envelope):
            raise RuntimeError("handler is broken")

        subscribe("test.event.raised", exploding_handler)
        try:
            envelope = publish("test.event.raised", {"ok": True})
            self.assertEqual(envelope.payload, {"ok": True})
        finally:
            unsubscribe("test.event.raised", exploding_handler)

    def test_envelope_is_json_serialisable(self):
        import json

        from apps.common.events import publish

        envelope = publish("test.event.serialise", {"user_id": "abc", "count": 3})
        json.dumps(envelope.to_dict())  # must not raise
