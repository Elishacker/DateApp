"""The ``{% icon %}`` tag.

The only presentation helper in the platform. It emits a ``<use>`` reference
into the Bootstrap Icons sprite, which means:

  * one HTTP request for every icon on the site, cached forever;
  * icons inherit ``currentColor``, so they theme themselves in light and dark;
  * no emoji, which render differently on every OS and cannot be styled.

    {% icon "heart-fill" %}
    {% icon "patch-check-fill" class="text-ok" size=20 label="Verified" %}

Names come from :file:`static/img/icons.svg`. An unknown name renders nothing
rather than a broken glyph.
"""
from django import template
from django.templatetags.static import static
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()

#: Kept in sync with the sprite by ``python manage.py check_icons``.
AVAILABLE = {
    "fire", "star", "star-fill", "heart", "heart-fill", "chat-heart-fill",
    "chat-dots-fill", "bell-fill", "person-circle", "sliders2", "patch-check-fill",
    "gem", "shield-lock-fill", "gear-fill", "shield-check", "flag-fill",
    "bar-chart-line-fill", "compass-fill", "journal-text", "person-badge-fill",
    "x-lg", "arrow-counterclockwise", "arrow-right", "send-fill", "geo-alt-fill",
    "briefcase-fill", "camera-fill", "mortarboard-fill", "circle-fill",
    "clock-history", "check2", "check2-all", "paperclip", "mic-fill", "image",
    "emoji-smile", "three-dots", "trash3", "check-circle-fill", "x-circle-fill",
    "exclamation-triangle-fill", "info-circle-fill", "shield-exclamation",
    "lock-fill", "box-arrow-right", "envelope-fill", "telephone-fill", "receipt",
    "credit-card-2-back-fill", "people-fill", "globe-americas", "search",
    "plus-lg", "pencil-square", "eye-fill", "hourglass-split",
    "lightning-charge-fill", "award-fill", "list",
}


@register.simple_tag
def icon(name, css_class="", size=16, label=""):
    """Render one sprite icon.

    ``label`` makes it meaningful to a screen reader; without one the icon is
    marked decorative, which is correct when adjacent text already says it.
    """
    if name not in AVAILABLE:
        return ""

    sprite = static("img/icons.svg")
    classes = f"icon {css_class}".strip()

    accessibility = (
        format_html('role="img" aria-label="{}"', label) if label
        else mark_safe('aria-hidden="true"')
    )

    return format_html(
        '<svg class="{}" width="{}" height="{}" fill="currentColor" {}>'
        '<use href="{}#i-{}"></use></svg>',
        classes, size, size, accessibility, sprite, name,
    )
