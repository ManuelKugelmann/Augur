"""Augur shared config and helpers — used by both publish and score servers."""

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Brand + horizon config
# ---------------------------------------------------------------------------

BRANDS = {
    "the": {
        "name": "The Augur", "locale": "en", "module": "general",
        "masthead": "THE AUGUR",
        "horizons": {"tomorrow": "tomorrow", "soon": "soon", "future": "future", "leap": "leap"},
        "image_prefix": "Editorial documentary photograph, photojournalistic style, natural lighting, high detail, 35mm lens. ",
        "disclaimer": "AI-generated speculation — not news. Not financial advice.",
        "accent_color": "#FFD700",
    },
    "der": {
        "name": "Der Augur", "locale": "de", "module": "general",
        "masthead": "DER AUGUR",
        "horizons": {"tomorrow": "morgen", "soon": "bald", "future": "zukunft", "leap": "sprung"},
        "image_prefix": "Editorial documentary photograph, photojournalistic style, natural lighting, high detail, 35mm lens. ",
        "disclaimer": "KI-generierte Spekulation — keine Nachricht. Keine Finanzberatung.",
        "accent_color": "#FFD700",
    },
    "financial": {
        "name": "Financial Augur", "locale": "en", "module": "markets",
        "masthead": "FINANCIAL AUGUR",
        "horizons": {"tomorrow": "tomorrow", "soon": "soon", "future": "future", "leap": "leap"},
        "image_prefix": "Professional financial editorial photograph, Bloomberg terminal aesthetic, corporate environment, clean lighting. ",
        "disclaimer": "AI-generated opinion — not financial advice.",
        "accent_color": "#00BFFF",
    },
    "finanz": {
        "name": "Finanz Augur", "locale": "de", "module": "markets",
        "masthead": "FINANZ AUGUR",
        "horizons": {"tomorrow": "morgen", "soon": "bald", "future": "zukunft", "leap": "sprung"},
        "image_prefix": "Professional financial editorial photograph, Bloomberg terminal aesthetic, corporate environment, clean lighting. ",
        "disclaimer": "KI-generierte Einschätzung — keine Finanzberatung.",
        "accent_color": "#00BFFF",
    },
}

# Horizon → fictive date offset (days/months/years from publish date)
HORIZON_OFFSETS = {
    "tomorrow": {"days": 3},
    "soon": {"months": 3},
    "future": {"years": 3},
    "leap": {"years": 30},
}

SECTION_LABELS = {
    "en": {"signal": "The Signal", "extrapolation": "The Extrapolation", "in_the_works": "In The Works"},
    "de": {"signal": "Das Signal", "extrapolation": "Die Extrapolation", "in_the_works": "In Arbeit"},
}

# Per-brand cron schedules: {brand: {horizon: cron_expression}}
SCHEDULES = {
    "the":       {"tomorrow": "0,6,12,18", "soon": "2",  "future": "3/mon", "leap": "3/mon"},
    "der":       {"tomorrow": "1,7,13,19", "soon": "4",  "future": "5/mon", "leap": "5/mon"},
    "financial": {"tomorrow": "2,8,14,20", "soon": "2",  "future": "6/mon", "leap": "6/mon"},
    "finanz":    {"tomorrow": "3,9,15,21", "soon": "4",  "future": "7/mon", "leap": "7/mon"},
}

# Horizon → days after publish when a prediction becomes scoreable
HORIZON_DAYS = {"tomorrow": 3, "soon": 90, "future": 1095, "leap": 10950}

# Section header patterns (EN/DE) for extracting prediction content from body
_SIGNAL_HEADERS = re.compile(r"^##\s+(?:The Signal|Das Signal)\s*$", re.MULTILINE)
_EXTRAP_HEADERS = re.compile(r"^##\s+(?:The Extrapolation|Die Extrapolation)\s*$", re.MULTILINE)
_ITW_HEADERS = re.compile(r"^##\s+(?:In The Works|In Arbeit)\s*$", re.MULTILINE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def site_dir() -> str:
    return os.environ.get("AUGUR_SITE_DIR", os.path.expanduser("~/augur-site"))


def site_base_url() -> str:
    return os.environ.get("AUGUR_SITE_URL", "https://augur.example.com")


def slugify(text: str, max_len: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len] or "untitled"


def compute_fictive_date(horizon: str, pub_date: datetime) -> str:
    """Compute the fictive target date from horizon offset."""
    offset = HORIZON_OFFSETS.get(horizon, {"days": 3})
    if "days" in offset:
        target = pub_date + timedelta(days=offset["days"])
    elif "months" in offset:
        import calendar
        m = pub_date.month + offset["months"]
        y = pub_date.year + (m - 1) // 12
        m = (m - 1) % 12 + 1
        max_day = calendar.monthrange(y, m)[1]
        d = min(pub_date.day, max_day)
        target = pub_date.replace(year=y, month=m, day=d)
    elif "years" in offset:
        import calendar
        y = pub_date.year + offset["years"]
        max_day = calendar.monthrange(y, pub_date.month)[1]
        d = min(pub_date.day, max_day)
        target = pub_date.replace(year=y, month=pub_date.month, day=d)
    else:
        target = pub_date + timedelta(days=3)
    return target.strftime("%Y-%m-%d")


def article_url(brand: str, horizon_slug: str, fictive_date: str) -> str:
    """Build the public article URL."""
    base = site_base_url().rstrip("/")
    return f"{base}/{brand}/{horizon_slug}/{fictive_date}"


def is_due(schedule: str, now: datetime) -> bool:
    """Check if a schedule expression matches the current time."""
    hour = now.hour
    minute = now.minute
    dow = now.weekday()

    if minute >= 15:
        return False

    if "/" in schedule:
        h, day = schedule.split("/")
        if day == "mon" and dow != 0:
            return False
        return hour == int(h)

    hours = [int(h) for h in schedule.split(",")]
    return hour in hours


def extract_sections(body: str) -> dict:
    """Extract signal/extrapolation/in_the_works from article body text."""
    sections: dict = {}
    sig_m = _SIGNAL_HEADERS.search(body)
    ext_m = _EXTRAP_HEADERS.search(body)
    itw_m = _ITW_HEADERS.search(body)

    boundaries = sorted(
        [(m.end(), name) for m, name in [
            (sig_m, "signal"), (ext_m, "extrapolation"), (itw_m, "in_the_works"),
        ] if m],
        key=lambda x: x[0],
    )

    for i, (start, name) in enumerate(boundaries):
        end = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(body)
        text = body[start:end]
        next_header = re.search(r"^##\s+", text, re.MULTILINE)
        if next_header and next_header.start() > 0:
            text = text[:next_header.start()]
        sections[name] = text.strip()

    return sections


def parse_front_matter(text: str) -> tuple[dict, str]:
    """Parse YAML front matter from Jekyll markdown. Returns (fm_dict, body)."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("---", 3)
    if end == -1:
        return {}, text
    fm_raw = text[3:end].strip()
    body = text[end + 3:].lstrip("\n")

    fm: dict = {}
    lines = fm_raw.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if ":" not in line or line.startswith("-") or line.startswith(" "):
            i += 1
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if not key:
            i += 1
            continue

        if val == "" and i + 1 < len(lines) and lines[i + 1].startswith((" ", "-")):
            block_lines = []
            j = i + 1
            while j < len(lines) and (lines[j].startswith((" ", "-")) or lines[j].strip() == ""):
                block_lines.append(lines[j])
                j += 1
            block = "\n".join(block_lines)
            parsed = _parse_yaml_block(block)
            fm[key] = parsed
            i = j
            continue

        fm[key] = _parse_yaml_value(val)
        i += 1

    return fm, body


def _parse_yaml_value(val: str):
    """Parse a single YAML value string."""
    if val == "" or val.lower() == "null":
        return None
    if val.lower() == "true":
        return True
    if val.lower() == "false":
        return False
    if val.startswith('"') and val.endswith('"'):
        return val[1:-1]
    if val.startswith("["):
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            return val
    if val.replace(".", "", 1).lstrip("-").isdigit():
        return float(val) if "." in val else int(val)
    return val


def _parse_yaml_block(block: str) -> list:
    """Parse indented YAML block (list of dicts or simple list)."""
    items: list = []
    current: dict = {}
    for line in block.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- ") and ":" in stripped:
            if current:
                items.append(current)
            current = {}
            kv = stripped[2:]
            k, _, v = kv.partition(":")
            current[k.strip()] = _parse_yaml_value(v.strip())
        elif stripped.startswith("-"):
            if current:
                items.append(current)
                current = {}
            items.append(_parse_yaml_value(stripped[1:].strip()))
        elif ":" in stripped and current is not None:
            k, _, v = stripped.partition(":")
            current[k.strip()] = _parse_yaml_value(v.strip())
    if current:
        items.append(current)
    return items


def find_articles(site: str, brand: str = "", horizon: str = "") -> list[Path]:
    """Find all Jekyll post files, optionally filtered by brand/horizon."""
    posts_dir = Path(site) / "_posts"
    if not posts_dir.exists():
        return []

    if brand and horizon:
        target = posts_dir / brand / horizon
        if not target.exists():
            return []
        return sorted(target.glob("*.md"), reverse=True)
    elif brand:
        target = posts_dir / brand
        if not target.exists():
            return []
        return sorted(target.rglob("*.md"), reverse=True)
    elif horizon:
        articles = []
        for brand_dir in sorted(posts_dir.iterdir()):
            if not brand_dir.is_dir():
                continue
            target = brand_dir / horizon
            if target.exists():
                articles.extend(target.glob("*.md"))
        return sorted(articles, reverse=True)
    else:
        return sorted(posts_dir.rglob("*.md"), reverse=True)


def to_yaml(obj: dict, indent: int = 0) -> str:
    """Minimal YAML serializer for front matter."""
    pad = "  " * indent
    out = ""
    for key, val in obj.items():
        if val is None:
            out += f"{pad}{key}:\n"
        elif isinstance(val, str):
            if any(c in val for c in ":#{}\n[]") or val.startswith(("'", '"')):
                out += f"{pad}{key}: {json.dumps(val)}\n"
            else:
                out += f'{pad}{key}: "{val}"\n'
        elif isinstance(val, bool):
            out += f"{pad}{key}: {'true' if val else 'false'}\n"
        elif isinstance(val, (int, float)):
            out += f"{pad}{key}: {val}\n"
        elif isinstance(val, list):
            if not val:
                out += f"{pad}{key}: []\n"
            elif isinstance(val[0], str):
                out += f"{pad}{key}: [{', '.join(json.dumps(v) for v in val)}]\n"
            elif isinstance(val[0], dict):
                out += f"{pad}{key}:\n"
                for item in val:
                    entries = list(item.items())
                    out += f"{pad}  - {entries[0][0]}: {json.dumps(entries[0][1])}\n"
                    for k, v in entries[1:]:
                        out += f"{pad}    {k}: {json.dumps(v)}\n"
            else:
                out += f"{pad}{key}: {json.dumps(val)}\n"
        elif isinstance(val, dict):
            out += f"{pad}{key}:\n{to_yaml(val, indent + 1)}"
    return out


def apply_watermark(image_path: str) -> None:
    """Apply AI-GENERATED watermark bar to bottom of image."""
    from PIL import Image, ImageDraw, ImageFont

    text = "AI-GENERATED \u00b7 NOT A PHOTO"
    img = Image.open(image_path).convert("RGBA")
    w, h = img.size
    bar_h = max(24, round(h * 0.035))

    bar = Image.new("RGBA", (w, bar_h), (0, 0, 0, 192))
    draw = ImageDraw.Draw(bar)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", round(bar_h * 0.5))
    except OSError:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    draw.text(((w - bbox[2] + bbox[0]) // 2, (bar_h - bbox[3] + bbox[1]) // 2),
              text, fill=(255, 255, 255, 230), font=font)

    composite = Image.new("RGBA", img.size)
    composite.paste(img, (0, 0))
    composite.paste(bar, (0, h - bar_h), bar)
    composite.convert("RGB").save(image_path)
