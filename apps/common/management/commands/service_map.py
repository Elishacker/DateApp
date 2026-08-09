"""Print the live service graph: contracts, dependencies and event wiring.

    python manage.py service_map
    python manage.py service_map --events
"""
import importlib

from django.core.management.base import BaseCommand

from apps.common.events import registered_handlers
from apps.common.registry import ServiceRegistry, services


class Command(BaseCommand):
    help = "Show every module's public contract, dependencies and event handlers."

    def add_arguments(self, parser):
        parser.add_argument("--events", action="store_true", help="Show event subscriptions.")
        parser.add_argument("--methods", action="store_true", help="Show interface methods.")

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("\nZynora service graph\n"))

        for name in ServiceRegistry.LOCAL_MODULES:
            try:
                interface = services.resolve(name)
                description = interface.describe()
            except Exception as exc:  # noqa: BLE001
                self.stdout.write(self.style.ERROR(f"  {name:<16} unavailable ({exc})"))
                continue

            deps = ", ".join(description["depends_on"]) or "—"
            self.stdout.write(f"  {self.style.SUCCESS(name.ljust(16))} depends on: {deps}")
            if options["methods"]:
                for method in description["methods"]:
                    self.stdout.write(f"      · {method}()")

        if options["events"]:
            self.stdout.write(self.style.MIGRATE_HEADING("\nEvent subscriptions\n"))
            # Import signal modules so subscriptions register.
            for name in ServiceRegistry.LOCAL_MODULES:
                try:
                    importlib.import_module(f"apps.{name}.signals")
                except ModuleNotFoundError:
                    continue
            handlers = registered_handlers()
            if not handlers:
                self.stdout.write("  (none registered)")
            for event, subscribers in sorted(handlers.items()):
                self.stdout.write(f"  {self.style.WARNING(event)}")
                for subscriber in subscribers:
                    self.stdout.write(f"      -> {subscriber}")
        self.stdout.write("")
