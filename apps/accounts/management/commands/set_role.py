"""Grant or revoke a staff role.

    python manage.py set_role alice@example.com moderator
    python manage.py set_role alice@example.com member      # revoke
    python manage.py set_role --list                        # who has what

Role changes are audited: the command publishes through the accounts contract,
so the change lands in the audit trail like any other privileged action.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.roles import ROLE_CAPABILITIES, capabilities_for
from apps.common.registry import services


class Command(BaseCommand):
    help = "Assign a role to a user, or list current staff."

    def add_arguments(self, parser):
        parser.add_argument("email", nargs="?", help="Account email address.")
        parser.add_argument("role", nargs="?", choices=sorted(ROLE_CAPABILITIES),
                            help="Role to assign.")
        parser.add_argument("--list", action="store_true", help="List staff accounts.")
        parser.add_argument("--roles", action="store_true",
                            help="Show every role and its capabilities.")

    def handle(self, *args, **options):
        if options["roles"]:
            return self._show_roles()
        if options["list"]:
            return self._list_staff()

        if not options["email"] or not options["role"]:
            raise CommandError("Provide an email and a role, or use --list / --roles.")

        from django.contrib.auth import get_user_model

        user = get_user_model().objects.filter(email__iexact=options["email"]).first()
        if not user:
            raise CommandError(f"No account with email '{options['email']}'.")

        previous = user.role
        result = services.accounts.set_role(str(user.id), options["role"])

        self.stdout.write(self.style.SUCCESS(
            f"\n✓ {user.email}: {previous} → {result['role']}"
        ))
        self.stdout.write(f"  Django admin access: {user.is_staff}")
        self.stdout.write("  Capabilities:")
        for capability in result["capabilities"]:
            self.stdout.write(f"    · {capability}")
        self.stdout.write("")

    def _list_staff(self):
        staff = services.accounts.list_staff()
        if not staff:
            self.stdout.write("No staff accounts. Grant one with:")
            self.stdout.write("  python manage.py set_role you@example.com admin")
            return

        self.stdout.write(self.style.MIGRATE_HEADING("\nStaff accounts\n"))
        for row in staff:
            marker = " (superuser)" if row["is_superuser"] else ""
            self.stdout.write(f"  {row['label']:<14} {row['email']}{marker}")
        self.stdout.write("")

    def _show_roles(self):
        self.stdout.write(self.style.MIGRATE_HEADING("\nRoles and capabilities\n"))
        for role in sorted(ROLE_CAPABILITIES):
            capabilities = sorted(capabilities_for(role))
            self.stdout.write(self.style.SUCCESS(f"  {role}"))
            if not capabilities:
                self.stdout.write("    (no privileged capabilities)")
            for capability in capabilities:
                self.stdout.write(f"    · {capability}")
        self.stdout.write("")
