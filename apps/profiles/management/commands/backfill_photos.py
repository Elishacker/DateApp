"""Generate a placeholder photo for every member who has none.

    python manage.py backfill_photos
    python manage.py backfill_photos --force   # replace generated ones too

Members without an approved photo are invisible in Discover, because
``with_photos_only`` defaults on — that restriction is deliberate. This command
keeps demo and development data usable without weakening it.

Avatars are drawn locally with Pillow: a deterministic two-tone gradient derived
from the user id, with the member's initial on top. No network, no third-party
placeholder service, and the same user always gets the same image.
"""
import hashlib
import io
import math

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from PIL import Image, ImageDraw, ImageFont

from apps.profiles.models import Profile, ProfilePhoto
from apps.profiles.services import PhotoService

SIZE = 900
#: Palette pairs chosen to stay legible behind white text.
PALETTES = [
    ((124, 58, 237), (236, 72, 153)),    # violet  -> pink
    ((14, 165, 233), (79, 70, 229)),     # sky     -> indigo
    ((236, 72, 153), (249, 115, 22)),    # pink    -> orange
    ((16, 185, 129), (14, 165, 233)),    # emerald -> sky
    ((249, 115, 22), (220, 38, 38)),     # orange  -> red
    ((79, 70, 229), (14, 116, 144)),     # indigo  -> teal
    ((219, 39, 119), (124, 58, 237)),    # fuchsia -> violet
    ((5, 150, 105), (101, 163, 13)),     # green   -> lime
]


class Command(BaseCommand):
    help = "Create a generated placeholder photo for members with no photos."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true",
                            help="Regenerate even for members who already have photos.")
        parser.add_argument("--count", type=int, default=2,
                            help="Photos to generate per member (default 2).")
        parser.add_argument("--only-demo", action="store_true",
                            help="Restrict to @demo.zynora.app accounts.")

    @transaction.atomic
    def handle(self, *args, **options):
        profiles = Profile.objects.select_related("user")
        if options["only_demo"]:
            profiles = profiles.filter(user__email__endswith="@demo.zynora.app")
        if not options["force"]:
            profiles = profiles.filter(photo_count=0)

        total = profiles.count()
        if not total:
            self.stdout.write(self.style.SUCCESS(
                "Every member already has a photo — nothing to do."))
            return

        self.stdout.write(f"Generating photos for {total} member(s)…")

        made = 0
        for profile in profiles.iterator():
            user = profile.user
            if options["force"]:
                ProfilePhoto.objects.filter(user=user).delete()

            for index in range(options["count"]):
                image = self._render(user, index)
                photo = ProfilePhoto.objects.create(
                    user=user,
                    caption="",
                    position=index,
                    is_primary=index == 0,
                    file_size=image.size,
                    width=SIZE,
                    height=SIZE,
                )
                photo.image.save(f"{user.username}-{index}.jpg", image, save=True)

                # Generated images bypass the review queue — there is nothing to
                # moderate, and leaving them pending would keep the feed empty.
                photo.moderation_status = ProfilePhoto.ModerationStatus.APPROVED
                photo.moderation_note = "Generated placeholder"
                photo.save(update_fields=["moderation_status", "moderation_note"])
                made += 1

            PhotoService._sync_profile(profile)

        self.stdout.write(self.style.SUCCESS(
            f"\n✓ {made} photo(s) created for {total} member(s)."))
        self.stdout.write(
            f"  Members now visible in Discover: "
            f"{Profile.objects.filter(photo_count__gt=0).count()}")

    # ------------------------------------------------------------------
    def _render(self, user, index):
        """Deterministic gradient avatar with the member's initial."""
        seed = int(hashlib.sha256(f"{user.id}:{index}".encode()).hexdigest()[:8], 16)
        start, end = PALETTES[seed % len(PALETTES)]
        angle = (seed >> 8) % 360

        image = Image.new("RGB", (SIZE, SIZE))
        draw = ImageDraw.Draw(image)

        # Linear gradient along `angle`, drawn one row of the projection at a time.
        radians = math.radians(angle)
        dx, dy = math.cos(radians), math.sin(radians)
        span = abs(dx) * SIZE + abs(dy) * SIZE
        for position in range(int(span)):
            ratio = position / span
            colour = tuple(
                int(start[channel] + (end[channel] - start[channel]) * ratio)
                for channel in range(3)
            )
            # Draw the iso-line perpendicular to the gradient direction.
            if abs(dx) > abs(dy):
                x = position - (SIZE if dx < 0 else 0)
                draw.line([(x, 0), (x - dy / dx * SIZE if dx else x, SIZE)],
                          fill=colour, width=2)
            else:
                y = position - (SIZE if dy < 0 else 0)
                draw.line([(0, y), (SIZE, y - dx / dy * SIZE if dy else y)],
                          fill=colour, width=2)

        # Soft vignette so white text stays readable on light palettes.
        overlay = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        ImageDraw.Draw(overlay).ellipse(
            [-SIZE // 3, -SIZE // 3, SIZE + SIZE // 3, SIZE + SIZE // 3],
            fill=(0, 0, 0, 38),
        )
        image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")

        draw = ImageDraw.Draw(image)
        initial = (user.first_name or user.username or "?")[0].upper()
        font = self._font(int(SIZE * 0.42))

        box = draw.textbbox((0, 0), initial, font=font)
        draw.text(
            ((SIZE - (box[2] - box[0])) / 2 - box[0],
             (SIZE - (box[3] - box[1])) / 2 - box[1]),
            initial, font=font, fill=(255, 255, 255, 235),
        )

        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=88, optimize=True)
        buffer.seek(0)
        return ContentFile(buffer.read())

    @staticmethod
    def _font(size):
        for path in (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
        ):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
        return ImageFont.load_default()
