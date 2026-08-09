"""Verify the icon system is internally consistent.

    python manage.py check_icons

Catches the three ways it can silently break:
  * a template uses ``{% icon %}`` without ``{% load icons %}`` (500 at render);
  * a template references a name the sprite does not contain (blank space);
  * the tag's ``AVAILABLE`` set has drifted from the sprite file.

Also fails on any emoji left in a template, since those were what the icon
system replaced.
"""
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.common.templatetags.icons import AVAILABLE

#: Pictographs only. Arrows (→ ↔ ←) and typographic marks are punctuation and
#: belong in prose — it is emoji standing in for interface icons we care about.
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⬀-⯿️]")


class Command(BaseCommand):
    help = "Check icon usage against the sprite."

    def handle(self, *args, **options):
        base = Path(settings.BASE_DIR)
        sprite_path = base / "static" / "img" / "icons.svg"

        if not sprite_path.exists():
            self.stdout.write(self.style.ERROR(f"Sprite missing: {sprite_path}"))
            raise SystemExit(1)

        in_sprite = set(re.findall(r'id="i-([^"]+)"', sprite_path.read_text()))
        problems = []

        # 1. The tag's whitelist must match the sprite exactly.
        for name in sorted(AVAILABLE - in_sprite):
            problems.append(("icons.py", 0, f"'{name}' is whitelisted but not in the sprite"))
        for name in sorted(in_sprite - AVAILABLE):
            problems.append(("icons.py", 0, f"'{name}' is in the sprite but not whitelisted"))

        # 2. Template usage.
        raw_output = re.compile(r"\{\{[^}]*\bicon\b[^}]*\}\}")

        for template in sorted((base / "templates").rglob("*.html")):
            text = template.read_text()
            rel = template.relative_to(base)
            uses = re.findall(r'\{%\s*icon\s+"([^"]+)"', text)
            has_tag = re.search(r"\{%\s*icon\s", text)

            if has_tag and "load icons" not in text and "load static icons" not in text:
                problems.append((str(rel), 1, "uses {% icon %} without {% load icons %}"))

            for name in uses:
                if name not in in_sprite:
                    problems.append((str(rel), 0, f"unknown icon '{name}'"))

            # An icon *name* printed as a variable renders as literal text —
            # exactly the bug that shipped "shield-check" into the sidebar.
            for line_no, line in enumerate(text.splitlines(), start=1):
                if raw_output.search(line):
                    problems.append((
                        str(rel), line_no,
                        "icon name printed as text — use {% icon <var> %} instead",
                    ))

            for line_no, line in enumerate(text.splitlines(), start=1):
                if EMOJI.search(line):
                    problems.append((str(rel), line_no, "emoji found — use {% icon %}"))

        # 3. Python source should name icons, not carry emoji.
        for source in sorted((base / "apps").rglob("*.py")):
            if "migrations" in source.parts or "management" in source.parts:
                continue  # CLI output may use ✓/✗ legitimately
            text = source.read_text()
            for line_no, line in enumerate(text.splitlines(), start=1):
                if EMOJI.search(line):
                    problems.append((
                        str(source.relative_to(base)), line_no,
                        "emoji in Python — store a sprite icon name instead",
                    ))

        if not problems:
            self.stdout.write(self.style.SUCCESS(
                f"✓ icon system clean — {len(in_sprite)} icons, all references valid."
            ))
            return

        self.stdout.write(self.style.ERROR(f"✗ {len(problems)} icon problem(s):\n"))
        for path, line, message in problems:
            location = f"{path}:{line}" if line else path
            self.stdout.write(f"  {location}  {message}")
        raise SystemExit(1)
