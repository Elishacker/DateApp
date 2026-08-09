"""Small pure helpers used across modules."""
import hashlib
import math
import re
import secrets
import unicodedata
from datetime import date

from django.utils import timezone

from .constants import EARTH_RADIUS_KM


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in kilometres, or ``None`` if a point is missing."""
    if None in (lat1, lon1, lat2, lon2):
        return None
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    d_phi = p2 - p1
    d_lambda = math.radians(float(lon2) - float(lon1))
    a = math.sin(d_phi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(d_lambda / 2) ** 2
    return round(2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a)), 2)


def bounding_box(lat, lon, radius_km):
    """Cheap SQL-friendly pre-filter before the exact haversine pass."""
    lat, lon = float(lat), float(lon)
    lat_delta = radius_km / 111.0
    cos_lat = math.cos(math.radians(lat)) or 1e-6
    lon_delta = radius_km / (111.0 * abs(cos_lat))
    return (lat - lat_delta, lat + lat_delta, lon - lon_delta, lon + lon_delta)


def calculate_age(born):
    if not born:
        return None
    today = date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def generate_token(length=48):
    return secrets.token_urlsafe(length)[:length]


def generate_numeric_code(digits=6):
    return "".join(secrets.choice("0123456789") for _ in range(digits))


def hash_token(raw):
    """Tokens are stored hashed so a database leak cannot be replayed."""
    return hashlib.sha256(raw.encode()).hexdigest()


def client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def user_agent(request):
    return request.META.get("HTTP_USER_AGENT", "")[:512]


def slugify_unique(value, model, field="slug"):
    base = re.sub(r"[^\w\s-]", "", unicodedata.normalize("NFKD", value)).strip().lower()
    base = re.sub(r"[-\s]+", "-", base) or "item"
    slug, index = base, 1
    while model.objects.filter(**{field: slug}).exists():
        index += 1
        slug = f"{base}-{index}"
    return slug


def humanize_delta(moment):
    if not moment:
        return "never"
    seconds = (timezone.now() - moment).total_seconds()
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    if seconds < 604800:
        return f"{int(seconds // 86400)}d ago"
    return moment.strftime("%d %b %Y")


def mask_email(value):
    if not value or "@" not in value:
        return value
    name, domain = value.split("@", 1)
    visible = name[:2] if len(name) > 2 else name[:1]
    return f"{visible}{'*' * max(len(name) - len(visible), 1)}@{domain}"


def mask_phone(value):
    if not value or len(value) < 4:
        return value
    return f"{'*' * (len(value) - 4)}{value[-4:]}"
