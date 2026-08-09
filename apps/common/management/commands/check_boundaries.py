"""Static analysis that keeps the service boundaries honest.

Run it in CI. It fails the build when a module reaches into another module's
internals instead of going through ``interface.py`` / the registry / the bus::

    python manage.py check_boundaries

Violations reported:
  * importing another module's ``models``, ``services``, ``forms``, ``tasks``,
    ``admin``, ``selectors`` or ``consumers``;
  * declaring a ForeignKey/OneToOne/ManyToMany to a model owned by another
    module (``AUTH_USER_MODEL`` is exempt — identity is shared);
  * a module missing its ``interface.py`` contract.
"""
import ast
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

PRIVATE_SUBMODULES = {
    "models", "services", "selectors", "forms", "tasks", "admin",
    "consumers", "signals", "managers", "serializers", "views",
}

#: Modules everyone may import freely — shared kernel, not a service.
SHARED = {"common", "api"}

RELATION_RE = re.compile(
    r"models\.(?:ForeignKey|OneToOneField|ManyToManyField)\(\s*[\"']([\w.]+)[\"']"
)


class Command(BaseCommand):
    help = "Verify that service modules only talk through their public contracts."

    def add_arguments(self, parser):
        parser.add_argument("--module", help="Check a single module only.")
        parser.add_argument("--strict", action="store_true",
                            help="Exit non-zero on any violation (default in CI).")

    def handle(self, *args, **options):
        root = Path(settings.BASE_DIR) / "apps"
        target = options.get("module")
        modules = sorted(
            p.name for p in root.iterdir()
            if p.is_dir() and (p / "__init__.py").exists()
        )
        if target:
            modules = [m for m in modules if m == target]

        violations = []
        for module in modules:
            if module in SHARED:
                continue
            violations.extend(self._check_module(root / module, module, set(modules)))

        self._report(violations, modules)

        if violations and options.get("strict", True):
            raise SystemExit(1)

    # ------------------------------------------------------------------
    def _check_module(self, path, module, known_modules):
        found = []

        if not (path / "interface.py").exists():
            found.append((module, "interface.py", 0,
                          "module has no public interface.py contract"))

        for file in sorted(path.rglob("*.py")):
            if "migrations" in file.parts:
                continue
            source = file.read_text(encoding="utf-8")
            rel = file.relative_to(path.parent.parent)

            found.extend(self._check_imports(source, rel, module, known_modules))
            if file.name == "models.py":
                found.extend(self._check_relations(source, rel, module))

        return found

    def _check_imports(self, source, rel, module, known_modules):
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:  # pragma: no cover - developer error
            return [(module, str(rel), exc.lineno or 0, f"syntax error: {exc.msg}")]

        problems = []
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names.append((node.module, node.lineno))
            elif isinstance(node, ast.Import):
                names.extend((alias.name, node.lineno) for alias in node.names)

            for dotted, lineno in names:
                parts = dotted.split(".")
                if len(parts) < 3 or parts[0] != "apps":
                    continue
                other, submodule = parts[1], parts[2]
                if other == module or other in SHARED or other not in known_modules:
                    continue
                if submodule in PRIVATE_SUBMODULES:
                    problems.append((
                        module, str(rel), lineno,
                        f"imports private '{dotted}' — use "
                        f"services.{other} or an event instead",
                    ))
        return problems

    def _check_relations(self, source, rel, module):
        problems = []
        for line_no, line in enumerate(source.splitlines(), start=1):
            match = RELATION_RE.search(line)
            if not match:
                continue
            target = match.group(1)
            if target in {settings.AUTH_USER_MODEL, "self"} or "." not in target:
                continue
            app_label = target.split(".")[0]
            if app_label != module and app_label not in SHARED:
                problems.append((
                    module, str(rel), line_no,
                    f"relation to '{target}' crosses a service boundary — "
                    f"use ServiceReference('{app_label}') instead",
                ))
        return problems

    # ------------------------------------------------------------------
    def _report(self, violations, modules):
        checked = len([m for m in modules if m not in SHARED])
        if not violations:
            self.stdout.write(self.style.SUCCESS(
                f"✓ {checked} service modules checked — all boundaries clean."
            ))
            return

        self.stdout.write(self.style.ERROR(
            f"✗ {len(violations)} boundary violation(s) across {checked} modules:\n"
        ))
        current = None
        for module, file, line, message in violations:
            if module != current:
                current = module
                self.stdout.write(self.style.WARNING(f"  {module}"))
            self.stdout.write(f"    {file}:{line}  {message}")
