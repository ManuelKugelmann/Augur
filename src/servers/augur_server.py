"""Augur MCP server — prediction article publishing + image generation tools.

The LLM uses existing T1-T4 MCP tools for research (like plan generation),
then calls these augur_* tools to publish the prediction as a Jekyll article.
Cron injects the target brand + horizon.
"""

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastmcp import FastMCP

mcp = FastMCP("augur", instructions=(
    "Augur prediction publisher. After researching signals via other tools, "
    "use augur tools to write Jekyll articles, generate images, and post to "
    "social media. Bluesky/Mastodon auto-post via API; X/Facebook/LinkedIn/"
    "Instagram send ntfy to admin with deep link. Brands: the (EN general), "
    "der (DE general), financial (EN markets), finanz (DE markets). "
    "Horizons: tomorrow, soon, future, leap.\n\n"
    "SCORING WORKFLOW: When due_now() returns score_pending items, you MUST "
    "score each one. For each pending prediction: (1) read its signal and "
    "extrapolation from the pending entry, (2) use news/finance/data tools "
    "to verify whether the prediction came true, (3) call score_prediction "
    "with outcome (confirmed/partial/wrong), a brief outcome_note, and "
    "evidence links from your research. Score ALL pending items before "
    "moving to publish tasks."
))

log = logging.getLogger("augur")

# ---------------------------------------------------------------------------
# Brand + horizon config (inlined to avoid cross-package imports)
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
# tomorrow=+3d, soon=+3mo, future=+3yr, leap=+30yr
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
# Cron format: "H M" pairs when this brand/horizon should run
SCHEDULES = {
    "the":       {"tomorrow": "0,6,12,18", "soon": "2",  "future": "3/mon", "leap": "3/mon"},
    "der":       {"tomorrow": "1,7,13,19", "soon": "4",  "future": "5/mon", "leap": "5/mon"},
    "financial": {"tomorrow": "2,8,14,20", "soon": "2",  "future": "6/mon", "leap": "6/mon"},
    "finanz":    {"tomorrow": "3,9,15,21", "soon": "4",  "future": "7/mon", "leap": "7/mon"},
}


def _is_due(schedule: str, now: datetime) -> bool:
    """Check if a schedule expression matches the current time.

    Formats:
        "0,6,12,18" — run at these hours (any minute in first 15)
        "2" — run at hour 2 daily
        "3/mon" — run at hour 3 on Mondays
    """
    hour = now.hour
    minute = now.minute
    dow = now.weekday()  # 0=Monday

    if minute >= 15:
        return False

    if "/" in schedule:
        h, day = schedule.split("/")
        if day == "mon" and dow != 0:
            return False
        return hour == int(h)

    hours = [int(h) for h in schedule.split(",")]
    return hour in hours


def _site_dir() -> str:
    return os.environ.get("AUGUR_SITE_DIR", os.path.expanduser("~/augur-site"))


def _site_base_url() -> str:
    return os.environ.get("AUGUR_SITE_URL", "https://augur.example.com")


def _slugify(text: str, max_len: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len] or "untitled"


def _compute_fictive_date(horizon: str, pub_date: datetime) -> str:
    """Compute the fictive target date from horizon offset.

    tomorrow=+3d, soon=+3mo, future=+3yr, leap=+30yr.
    Returns ISO date string.
    """
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


def _article_url(brand: str, horizon_slug: str, fictive_date: str) -> str:
    """Build the public article URL: {base}/{brand}/{horizon_slug}/{fictive_date}."""
    base = _site_base_url().rstrip("/")
    return f"{base}/{brand}/{horizon_slug}/{fictive_date}"


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_brands() -> dict:
    """List available Augur brands and their horizons."""
    return {
        k: {"name": v["name"], "locale": v["locale"], "module": v["module"],
             "horizons": v["horizons"]}
        for k, v in BRANDS.items()
    }


@mcp.tool()
async def due_now() -> dict:
    """Check what work is due right now: publishing + scoring.

    Called by the cron-news agent at each cron tick. Returns:
    - due: {brand, horizon} pairs to publish this cycle
    - score_pending: predictions past their horizon that need scoring,
      with full context (headline, signal, extrapolation, fictive_date)
      so the agent can research and score them automatically

    The agent should score ALL pending predictions FIRST (using other MCP
    tools to verify outcomes), then proceed to publish new articles.
    """
    now = datetime.now(timezone.utc)
    due: list[dict] = []

    for brand, horizons in SCHEDULES.items():
        for horizon, schedule in horizons.items():
            if _is_due(schedule, now):
                due.append({"brand": brand, "horizon": horizon})

    # Also surface pending scores so the agent can score them
    pending = await list_pending_scores(limit=10)
    score_due = pending.get("count", 0)

    return {
        "due": due, "checked_at": now.isoformat(), "count": len(due),
        "score_due": score_due,
        "score_pending": pending.get("pending", []) if score_due else [],
    }


@mcp.tool()
async def publish_article(
    brand: str,
    horizon: str,
    headline: str,
    signal: str,
    extrapolation: str,
    in_the_works: str,
    tags: list[str],
    sources: list[dict],
    image_prompt: str = "",
    confidence: str = "medium",
    sentiment_sector: str = "",
    sentiment_direction: str = "",
    sentiment_confidence: float = 0.0,
) -> dict:
    """Publish a prediction article as Jekyll Markdown with YAML front matter.

    Call this after researching signals via other tools. Provide the three
    article sections (signal, extrapolation, in_the_works) plus metadata.

    Returns the file path of the written article.
    """
    if brand not in BRANDS:
        return {"error": f"Unknown brand: {brand}. Use: {', '.join(BRANDS.keys())}"}
    valid_horizons = ("tomorrow", "soon", "future", "leap")
    if horizon not in valid_horizons:
        return {"error": f"horizon must be: {', '.join(valid_horizons)}"}

    b = BRANDS[brand]
    locale = b["locale"]
    horizon_slug = b["horizons"][horizon]
    labels = SECTION_LABELS[locale]
    now = datetime.now(timezone.utc)
    date_key = now.strftime("%Y-%m-%d")
    fictive_date = _compute_fictive_date(horizon, now)
    slug = _slugify(headline)
    url = _article_url(brand, horizon_slug, fictive_date)

    # Build front matter
    fm: dict = {
        "layout": "article",
        "brand": brand,
        "horizon": horizon,
        "categories": f"{brand}/{horizon_slug}",
        "date": date_key,
        "headline": headline,
        "fictive_date": fictive_date,
        "created_at": now.isoformat(),
        "tags": tags,
        "sources": sources,
        "model": os.environ.get("NEWS_MODEL", "claude-sonnet-4-5-20250514"),
        "confidence": confidence,
        "image_prompt": image_prompt,
        "article_url": url,
        "outcome": None,
        "outcome_note": None,
        "outcome_date": None,
    }

    if sentiment_sector:
        fm["sentiment_sector"] = sentiment_sector
        fm["sentiment_direction"] = sentiment_direction
        fm["sentiment_confidence"] = sentiment_confidence

    yaml = _to_yaml(fm)
    body = f"""## {labels['signal']}

{signal}

## {labels['extrapolation']}

{extrapolation}

## {labels['in_the_works']}

{in_the_works}
"""
    markdown = f"---\n{yaml}---\n\n{body}"

    # Write file
    site = _site_dir()
    file_path = os.path.join(
        site, "_posts", brand, horizon_slug, f"{date_key}-{slug}.md"
    )
    Path(file_path).parent.mkdir(parents=True, exist_ok=True)
    Path(file_path).write_text(markdown, encoding="utf-8")

    log.info("published: %s", file_path)
    return {
        "path": file_path, "brand": brand, "horizon": horizon,
        "headline": headline, "fictive_date": fictive_date, "article_url": url,
    }


@mcp.tool()
async def generate_article_image(
    prompt: str,
    brand: str,
    horizon: str,
    date_key: str = "",
) -> dict:
    """Generate a photorealistic image for a prediction article via Replicate.

    Uses FLUX.2 Klein 4B. The brand's image style prefix is automatically prepended.
    Returns the asset path relative to the site directory.
    """
    if brand not in BRANDS:
        return {"error": f"Unknown brand: {brand}"}

    b = BRANDS[brand]
    full_prompt = b["image_prefix"] + prompt
    date_key = date_key or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    site = _site_dir()
    image_prefix = f"{brand}-{horizon}-{date_key}"
    image_path = os.path.join(site, "assets", "images", f"{image_prefix}.webp")

    try:
        import asyncio

        import httpx
        token = os.environ.get("REPLICATE_API_TOKEN")
        if not token:
            return {"error": "REPLICATE_API_TOKEN not set"}

        # Create prediction
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.replicate.com/v1/models/black-forest-labs/flux-2-klein-4b/predictions",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"input": {
                    "prompt": full_prompt, "width": 1024, "height": 768,
                    "num_outputs": 1, "output_format": "webp", "output_quality": 85,
                }},
            )
            resp.raise_for_status()
            prediction = resp.json()

        # Poll for completion
        poll_url = prediction.get("urls", {}).get(
            "get", f"https://api.replicate.com/v1/predictions/{prediction['id']}"
        )
        async with httpx.AsyncClient(timeout=30) as client:
            for _ in range(60):
                if prediction["status"] in ("succeeded", "failed"):
                    break
                await asyncio.sleep(1)
                r = await client.get(poll_url, headers={"Authorization": f"Bearer {token}"})
                prediction = r.json()

        if prediction["status"] == "failed":
            return {"error": f"Image generation failed: {prediction.get('error')}"}

        image_url = prediction.get("output", [None])[0]
        if not image_url:
            return {"error": "No image URL in output"}

        # Download and save
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(image_url)
            r.raise_for_status()
            Path(image_path).parent.mkdir(parents=True, exist_ok=True)
            Path(image_path).write_bytes(r.content)

        # Apply watermark
        try:
            from PIL import Image, ImageDraw, ImageFont
            _apply_watermark(image_path)
        except ImportError:
            log.warning("Pillow not installed, skipping watermark")

        rel_path = f"assets/images/{image_prefix}.webp"
        log.info("generated image: %s", rel_path)
        return {"path": rel_path, "full_path": image_path}

    except Exception as exc:
        return {"error": f"Image generation failed: {exc}"}


# ---------------------------------------------------------------------------
# Social card compositing (1:1, 9:16, 16:9)
# ---------------------------------------------------------------------------

CARD_SIZES = {
    "1x1": (1080, 1080),
    "9x16": (1080, 1920),
    "16x9": (1200, 675),
}


def _generate_card(
    image_path: str, headline: str, brand_name: str,
    horizon_label: str, fictive_date: str, accent_color: str,
    width: int, height: int, output_path: str,
) -> None:
    """Generate a single social card with overlay text."""
    from PIL import Image, ImageDraw, ImageFont

    def _font(size: int):
        try:
            return ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", size)
        except OSError:
            return ImageFont.load_default()

    def _mono(size: int):
        try:
            return ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", size)
        except OSError:
            return ImageFont.load_default()

    # Load and cover-resize
    src = Image.open(image_path).convert("RGB")
    src_ratio = src.width / src.height
    target_ratio = width / height
    if src_ratio > target_ratio:
        new_h, new_w = height, round(src.width * (height / src.height))
    else:
        new_w, new_h = width, round(src.height * (width / src.width))
    src = src.resize((new_w, new_h), Image.LANCZOS)
    left, top = (new_w - width) // 2, (new_h - height) // 2
    card = src.crop((left, top, left + width, top + height))

    draw = ImageDraw.Draw(card, "RGBA")
    fs = round(width * 0.04)
    hfs = round(width * 0.05)
    pad = round(width * 0.06)

    # Semi-transparent overlay at bottom
    draw.rectangle([(0, round(height * 0.55)), (width, height)], fill=(0, 0, 0, 178))

    draw.text((pad, round(height * 0.60)), f"\u263d {brand_name}",
              fill=(255, 255, 255, 230), font=_font(fs))
    draw.text((pad, round(height * 0.66)),
              f"\u2500\u2500 {horizon_label.upper()} \u2500\u2500",
              fill=accent_color, font=_font(round(fs * 0.7)))

    max_chars = (width - 2 * pad) // max(1, round(hfs * 0.5))
    display = headline[:max_chars - 3] + "..." if len(headline) > max_chars else headline
    draw.text((pad, round(height * 0.74)), display,
              fill=(255, 255, 255), font=_font(hfs))
    draw.text((pad, round(height * 0.86)), f"Foreseen: {fictive_date}",
              fill=(255, 255, 255, 178), font=_mono(round(fs * 0.6)))
    draw.text((pad, round(height * 0.92)), "AI-generated speculation",
              fill=(255, 255, 255, 128), font=_mono(round(fs * 0.5)))
    draw.rectangle([(0, height - 4), (width, height)], fill=accent_color)

    card.convert("RGB").save(output_path, "WEBP", quality=85)


@mcp.tool()
async def generate_social_cards(
    image_path: str,
    headline: str,
    brand: str,
    horizon: str,
    fictive_date: str,
) -> dict:
    """Generate social sharing cards in 1:1, 9:16, 16:9 from an article image.

    Creates cropped/overlaid versions suitable for each social platform.
    Returns paths to generated card files.

    Args:
        image_path: Path to the source article image.
        headline: Article headline for overlay text.
        brand: Brand slug (the, der, financial, finanz).
        horizon: Horizon slug (tomorrow, soon, future, leap).
        fictive_date: The fictive target date for the overlay.
    """
    if brand not in BRANDS:
        return {"error": f"Unknown brand: {brand}"}
    if not Path(image_path).exists():
        return {"error": f"Image not found: {image_path}"}

    b = BRANDS[brand]
    brand_name = b["masthead"]
    accent = b.get("accent_color", "#FFD700")
    horizon_label = b["horizons"].get(horizon, horizon)

    site = _site_dir()
    out_dir = os.path.join(site, "assets", "cards", brand, horizon)
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    slug = _slugify(headline, 30)
    paths = {}

    try:
        for ratio, (w, h) in CARD_SIZES.items():
            out_path = os.path.join(out_dir, f"{slug}-{ratio}.webp")
            _generate_card(image_path, headline, brand_name, horizon_label,
                           fictive_date, accent, w, h, out_path)
            paths[ratio] = out_path
        return {"cards": paths, "count": len(paths)}
    except ImportError:
        return {"error": "Pillow not installed — run: pip install Pillow"}
    except Exception as e:
        return {"error": f"Card generation failed: {e}"}


# Platforms that support auto-posting via API
_AUTO_PLATFORMS = {"bluesky", "mastodon"}
# Platforms that need manual posting — admin gets ntfy with caption + deep link
_MANUAL_PLATFORMS = {"x", "facebook", "linkedin", "instagram"}

_NTFY_BASE = os.environ.get("NTFY_BASE_URL", "https://ntfy.sh")
_NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")


async def _post_bluesky(caption: str, article_url: str,
                        image_path: str = "") -> dict:
    """Post to Bluesky via AT Protocol, optionally with an image card."""
    import httpx

    handle = os.environ.get("BLUESKY_HANDLE", "")
    password = os.environ.get("BLUESKY_APP_PASSWORD", "")
    if not handle or not password:
        return {"error": "BLUESKY_HANDLE and BLUESKY_APP_PASSWORD not set"}

    pds = os.environ.get("BLUESKY_PDS", "https://bsky.social")

    async with httpx.AsyncClient(timeout=30) as client:
        # Create session
        r = await client.post(f"{pds}/xrpc/com.atproto.server.createSession",
                              json={"identifier": handle, "password": password})
        r.raise_for_status()
        session = r.json()
        token = session["accessJwt"]
        did = session["did"]
        auth_headers = {"Authorization": f"Bearer {token}"}

        # Upload image blob if provided
        embed = None
        if image_path and Path(image_path).exists():
            img_data = Path(image_path).read_bytes()
            mime = "image/webp" if image_path.endswith(".webp") else "image/jpeg"
            r = await client.post(
                f"{pds}/xrpc/com.atproto.repo.uploadBlob",
                headers={**auth_headers, "Content-Type": mime},
                content=img_data,
            )
            r.raise_for_status()
            blob = r.json().get("blob")
            if blob:
                embed = {
                    "$type": "app.bsky.embed.images",
                    "images": [{"alt": caption[:300], "image": blob}],
                }

        # Build post with link facet
        text = f"{caption}\n\n{article_url}"
        url_start = len(caption.encode("utf-8")) + 2
        url_end = url_start + len(article_url.encode("utf-8"))
        facets = [{
            "index": {"byteStart": url_start, "byteEnd": url_end},
            "features": [{"$type": "app.bsky.richtext.facet#link", "uri": article_url}],
        }]

        record = {
            "$type": "app.bsky.feed.post",
            "text": text,
            "facets": facets,
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
        if embed:
            record["embed"] = embed

        r = await client.post(
            f"{pds}/xrpc/com.atproto.repo.createRecord",
            headers=auth_headers,
            json={"repo": did, "collection": "app.bsky.feed.post", "record": record},
        )
        r.raise_for_status()
        data = r.json()
        return {"posted": True, "uri": data.get("uri", ""),
                "has_image": embed is not None}


async def _post_mastodon(caption: str, article_url: str,
                         image_path: str = "") -> dict:
    """Post to Mastodon via API, optionally with an image card."""
    import httpx

    token = os.environ.get("MASTODON_ACCESS_TOKEN", "")
    instance = os.environ.get("MASTODON_INSTANCE", "")
    if not token or not instance:
        return {"error": "MASTODON_ACCESS_TOKEN and MASTODON_INSTANCE not set"}

    instance = instance.rstrip("/")
    text = f"{caption}\n\n{article_url}"
    auth_headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=30) as client:
        # Upload image if provided
        media_ids = []
        if image_path and Path(image_path).exists():
            img_data = Path(image_path).read_bytes()
            mime = "image/webp" if image_path.endswith(".webp") else "image/jpeg"
            r = await client.post(
                f"{instance}/api/v2/media",
                headers=auth_headers,
                files={"file": ("card.webp", img_data, mime)},
                data={"description": caption[:1500]},
            )
            r.raise_for_status()
            media_ids.append(r.json()["id"])

        payload: dict = {"status": text, "visibility": "public"}
        if media_ids:
            payload["media_ids"] = media_ids

        r = await client.post(
            f"{instance}/api/v1/statuses",
            headers=auth_headers,
            json=payload,
        )
        r.raise_for_status()
        data = r.json()
        return {"posted": True, "url": data.get("url", ""),
                "has_image": bool(media_ids)}


async def _notify_manual_post(platform: str, brand: str, caption: str,
                              article_url: str) -> dict:
    """Send ntfy notification with deep link for manual social posting."""
    import httpx

    topic = _NTFY_TOPIC
    if not topic:
        return {"error": "NTFY_TOPIC not set — cannot notify admin"}

    b = BRANDS.get(brand, {})
    brand_name = b.get("name", brand)
    title = f"Post to {platform.title()} — {brand_name}"
    body = f"{caption}\n\n{article_url}"

    headers = {
        "Title": title,
        "Priority": "default",
        "Tags": f"mega,{platform}",
        "Click": article_url,
        "Actions": f"view, Open article, {article_url}",
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{_NTFY_BASE}/{topic}",
                                  content=body, headers=headers)
            r.raise_for_status()
        return {"notified": True, "platform": platform, "topic": topic}
    except Exception as e:
        return {"error": f"ntfy failed: {e}"}


@mcp.tool()
async def post_social(
    brand: str,
    platform: str,
    caption: str,
    article_url: str,
    image_path: str = "",
) -> dict:
    """Post or notify for a social media platform.

    Auto-posts to Bluesky and Mastodon via API (with optional image card).
    For X, Facebook, LinkedIn, and Instagram: sends an ntfy notification
    to the admin with the caption and a deep link to the article.

    Call once per platform after publish_article + generate_social_cards + push_site.
    For image_path, use the appropriate ratio from generate_social_cards:
    16:9 for Bluesky/X/Facebook/LinkedIn, 1:1 for Mastodon/Instagram.

    Args:
        brand: Brand slug (the, der, financial, finanz).
        platform: Target platform (bluesky, mastodon, x, facebook, linkedin, instagram).
        caption: The social media caption/text.
        article_url: Public URL of the published article (used as deep link).
        image_path: Optional path to a social card image to attach.
    """
    platform = platform.lower()
    all_platforms = _AUTO_PLATFORMS | _MANUAL_PLATFORMS
    if platform not in all_platforms:
        return {"error": f"Unknown platform: {platform}. Use: {', '.join(sorted(all_platforms))}"}

    if platform == "bluesky":
        return await _post_bluesky(caption, article_url, image_path)
    elif platform == "mastodon":
        return await _post_mastodon(caption, article_url, image_path)
    else:
        return await _notify_manual_post(platform, brand, caption, article_url)


@mcp.tool()
async def push_site(message: str = "") -> dict:
    """Commit and push the augur-site to trigger GitHub Pages deployment.

    Call this after publishing articles and generating images.
    """
    import asyncio
    site = _site_dir()
    branch = os.environ.get("AUGUR_SITE_BRANCH", "augur_news")

    async def _run(cmd: list[str]) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=site,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode or 0, stdout.decode(), stderr.decode()

    await _run(["git", "add", "."])

    rc, status_out, _ = await _run(["git", "status", "--porcelain"])
    if not status_out.strip():
        return {"status": "no changes to push"}

    commit_msg = message or f"augur: new predictions {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
    await _run(["git", "commit", "-m", commit_msg])

    # Push with retry
    for attempt in range(5):
        rc, _, stderr = await _run(["git", "push", "-u", "origin", branch])
        if rc == 0:
            return {"status": "pushed", "branch": branch}
        if attempt < 4:
            await asyncio.sleep(2 ** (attempt + 1))

    return {"error": f"push failed after 5 attempts: {stderr}"}


# ---------------------------------------------------------------------------
# Scorecard tools
# ---------------------------------------------------------------------------

# Horizon → days after publish when a prediction becomes scoreable
# tomorrow=+3d → scoreable after 3d, soon=+3mo → 90d, future=+3yr → 1095d, leap=+30yr → 10950d
HORIZON_DAYS = {"tomorrow": 3, "soon": 90, "future": 1095, "leap": 10950}

# Section header patterns (EN/DE) for extracting prediction content from body
_SIGNAL_HEADERS = re.compile(r"^##\s+(?:The Signal|Das Signal)\s*$", re.MULTILINE)
_EXTRAP_HEADERS = re.compile(r"^##\s+(?:The Extrapolation|Die Extrapolation)\s*$", re.MULTILINE)
_ITW_HEADERS = re.compile(r"^##\s+(?:In The Works|In Arbeit)\s*$", re.MULTILINE)


def _extract_sections(body: str) -> dict:
    """Extract signal/extrapolation/in_the_works from article body text."""
    sections: dict = {}
    # Find section boundaries
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
        # Strip from start to next header (which includes the "## " prefix)
        text = body[start:end]
        # Remove trailing header line if present
        next_header = re.search(r"^##\s+", text, re.MULTILINE)
        if next_header and next_header.start() > 0:
            text = text[:next_header.start()]
        sections[name] = text.strip()

    return sections


def _parse_front_matter(text: str) -> tuple[dict, str]:
    """Parse YAML front matter from Jekyll markdown. Returns (fm_dict, body).

    Handles multi-line values: lists of dicts (sources) and indented blocks.
    """
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

        # Check if next lines are indented (multi-line value)
        if val == "" and i + 1 < len(lines) and lines[i + 1].startswith((" ", "-")):
            # Collect all continuation lines
            block_lines = []
            j = i + 1
            while j < len(lines) and (lines[j].startswith((" ", "-")) or lines[j].strip() == ""):
                block_lines.append(lines[j])
                j += 1
            # Try to parse as YAML-like list of dicts
            block = "\n".join(block_lines)
            parsed = _parse_yaml_block(block)
            fm[key] = parsed
            i = j
            continue

        # Simple single-line value
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
            # New dict item: "- key: value"
            if current:
                items.append(current)
            current = {}
            kv = stripped[2:]
            k, _, v = kv.partition(":")
            current[k.strip()] = _parse_yaml_value(v.strip())
        elif stripped.startswith("-"):
            # Simple list item: "- value"
            if current:
                items.append(current)
                current = {}
            items.append(_parse_yaml_value(stripped[1:].strip()))
        elif ":" in stripped and current is not None:
            # Continuation key in current dict: "  key: value"
            k, _, v = stripped.partition(":")
            current[k.strip()] = _parse_yaml_value(v.strip())
    if current:
        items.append(current)
    return items


def _find_articles(site: str, brand: str = "", horizon: str = "") -> list[Path]:
    """Find all Jekyll post files, optionally filtered by brand/horizon.

    Uses directory structure (_posts/{brand}/{horizon}/) for filtering
    instead of reading every file — O(1) directory lookups vs O(n) file reads.
    """
    posts_dir = Path(site) / "_posts"
    if not posts_dir.exists():
        return []

    if brand and horizon:
        # Narrow: _posts/{brand}/{horizon}/*.md
        target = posts_dir / brand / horizon
        if not target.exists():
            return []
        return sorted(target.glob("*.md"), reverse=True)
    elif brand:
        # All horizons for one brand: _posts/{brand}/**/*.md
        target = posts_dir / brand
        if not target.exists():
            return []
        return sorted(target.rglob("*.md"), reverse=True)
    elif horizon:
        # One horizon across all brands: _posts/*/{horizon}/*.md
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


@mcp.tool()
async def score_prediction(
    article_path: str,
    outcome: str,
    outcome_note: str = "",
    evidence: list[dict] = [],
) -> dict:
    """Score (or re-score) a prediction article's outcome.

    Updates the front matter outcome fields in the Jekyll markdown file.
    Can be called multiple times — each scoring is appended to a score log
    alongside the article so the full history is preserved. The front matter
    always reflects the latest score.

    Args:
        article_path: Path to the article .md file (relative to site dir or absolute).
        outcome: One of "confirmed", "partial", "wrong".
        outcome_note: Brief explanation of why this outcome was assigned.
        evidence: List of sources backing the verdict, each {url, title?}.
    """
    if outcome not in ("confirmed", "partial", "wrong"):
        return {"error": "outcome must be: confirmed, partial, wrong"}

    site = _site_dir()
    path = Path(article_path)
    if not path.is_absolute():
        path = Path(site) / path

    if not path.exists():
        return {"error": f"Article not found: {path}"}

    text = path.read_text(encoding="utf-8")
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_full = datetime.now(timezone.utc).isoformat()

    # Replace outcome fields in front matter only (between --- markers)
    def _replace_field(content: str, field: str, value: str) -> str:
        if not content.startswith("---"):
            return content
        fm_end = content.find("---", 3)
        if fm_end == -1:
            return content
        fm_block = content[:fm_end]
        rest = content[fm_end:]
        pattern = re.compile(rf"^({re.escape(field)}:).*$", re.MULTILINE)
        if pattern.search(fm_block):
            fm_block = pattern.sub(rf'\1 "{value}"', fm_block)
        else:
            fm_block += f'{field}: "{value}"\n'
        return fm_block + rest

    text = _replace_field(text, "outcome", outcome)
    text = _replace_field(text, "outcome_date", now_iso)
    if outcome_note:
        text = _replace_field(text, "outcome_note", outcome_note)

    path.write_text(text, encoding="utf-8")

    # Append to score log (preserves full history for re-scoring)
    log_path = path.with_suffix(".scores.json")
    history: list = []
    if log_path.exists():
        try:
            history = json.loads(log_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            history = []

    entry = {"outcome": outcome, "outcome_date": now_iso, "scored_at": now_full}
    if outcome_note:
        entry["outcome_note"] = outcome_note
    if evidence:
        entry["evidence"] = evidence
    entry["revision"] = len(history) + 1
    history.append(entry)
    log_path.write_text(json.dumps(history, indent=2), encoding="utf-8")

    log.info("scored %s → %s (rev %d)", path.name, outcome, entry["revision"])
    result = {
        "path": str(path), "outcome": outcome, "outcome_date": now_iso,
        "revision": entry["revision"],
    }
    if evidence:
        result["evidence"] = evidence
    return result


@mcp.tool()
async def list_pending_scores(
    brand: str = "",
    horizon: str = "",
    include_scored: bool = False,
    limit: int = 50,
) -> dict:
    """List prediction articles that are past their horizon date and need scoring.

    By default lists only unscored articles. Set include_scored=True to also
    list previously scored articles for re-evaluation (e.g. revisiting a
    "partial" after more data becomes available).

    Args:
        brand: Filter by brand slug (optional).
        horizon: Filter by horizon (optional).
        include_scored: Include already-scored articles for re-scoring (default False).
        limit: Max articles to return (default 50).
    """
    site = _site_dir()
    articles = _find_articles(site, brand, horizon)
    now = datetime.now(timezone.utc)
    pending: list[dict] = []

    for path in articles:
        if len(pending) >= limit:
            break
        text = path.read_text(encoding="utf-8")
        fm, body = _parse_front_matter(text)

        # Skip already scored unless re-scoring requested
        current_outcome = fm.get("outcome")
        if current_outcome and not include_scored:
            continue

        # Check if past horizon window
        date_str = fm.get("date") or fm.get("fictive_date")
        if not date_str:
            continue
        try:
            pub_date = datetime.strptime(str(date_str), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue

        h = fm.get("horizon", "tomorrow")
        days_needed = HORIZON_DAYS.get(h, 3)
        if (now - pub_date).days < days_needed:
            continue

        # Check score log for revision count
        log_path = path.with_suffix(".scores.json")
        revision = 0
        if log_path.exists():
            try:
                revision = len(json.loads(log_path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, ValueError):
                pass

        # Extract prediction content so the agent can evaluate
        sections = _extract_sections(body)

        entry = {
            "path": str(path.relative_to(site)),
            "brand": fm.get("brand"),
            "horizon": h,
            "date": str(date_str),
            "fictive_date": fm.get("fictive_date", ""),
            "headline": fm.get("headline", path.stem),
            "signal": sections.get("signal", ""),
            "extrapolation": sections.get("extrapolation", ""),
            "tags": fm.get("tags", []),
            "confidence": fm.get("confidence", "medium"),
            "days_ago": (now - pub_date).days,
            "current_outcome": current_outcome,
            "revision": revision,
        }
        pending.append(entry)

    return {"pending": pending, "count": len(pending)}


@mcp.tool()
async def generate_scorecard(
    brand: str = "",
    horizon: str = "",
    last_n_days: int = 90,
) -> dict:
    """Generate an accuracy scorecard across scored predictions.

    Aggregates outcome stats and writes a Jekyll data file for site rendering.
    Returns summary stats including accuracy rate, counts, and per-brand breakdown.

    Args:
        brand: Filter by brand slug (optional, empty = all brands).
        horizon: Filter by horizon (optional, empty = all horizons).
        last_n_days: Only include articles from the last N days (default 90).
    """
    site = _site_dir()
    articles = _find_articles(site, brand, horizon)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=last_n_days)

    # Collect scored articles
    scored: list[dict] = []
    for path in articles:
        text = path.read_text(encoding="utf-8")
        fm, _ = _parse_front_matter(text)
        if not fm.get("outcome"):
            continue
        date_str = fm.get("date") or fm.get("fictive_date")
        if not date_str:
            continue
        try:
            pub_date = datetime.strptime(str(date_str), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
        if pub_date < cutoff:
            continue

        scored.append({
            "brand": fm.get("brand", "unknown"),
            "horizon": fm.get("horizon", "unknown"),
            "date": str(date_str),
            "headline": fm.get("headline", ""),
            "outcome": fm["outcome"],
            "outcome_note": fm.get("outcome_note", ""),
            "outcome_date": fm.get("outcome_date", ""),
            "confidence": fm.get("confidence", "medium"),
        })

    if not scored:
        return {"summary": {"total": 0, "accuracy": None}, "breakdown": {}, "articles": []}

    # Aggregate
    total = len(scored)
    confirmed = sum(1 for s in scored if s["outcome"] == "confirmed")
    partial = sum(1 for s in scored if s["outcome"] == "partial")
    wrong = sum(1 for s in scored if s["outcome"] == "wrong")
    accuracy = round((confirmed + partial * 0.5) / total, 3) if total else 0

    # Per-brand breakdown
    breakdown: dict[str, dict] = {}
    for s in scored:
        key = f"{s['brand']}/{s['horizon']}"
        if key not in breakdown:
            breakdown[key] = {"total": 0, "confirmed": 0, "partial": 0, "wrong": 0}
        breakdown[key]["total"] += 1
        breakdown[key][s["outcome"]] += 1
    for k, v in breakdown.items():
        t = v["total"]
        v["accuracy"] = round((v["confirmed"] + v["partial"] * 0.5) / t, 3) if t else 0

    summary = {
        "total": total,
        "confirmed": confirmed,
        "partial": partial,
        "wrong": wrong,
        "accuracy": accuracy,
        "period_days": last_n_days,
    }

    # Write scorecard data file for Jekyll
    data_dir = Path(site) / "_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    scorecard_data = {"generated_at": now.isoformat(), "summary": summary, "breakdown": breakdown}
    (data_dir / "scorecard.json").write_text(json.dumps(scorecard_data, indent=2), encoding="utf-8")

    log.info("scorecard: %d scored, accuracy=%.1f%%", total, accuracy * 100)
    return {"summary": summary, "breakdown": breakdown, "articles": scored}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _apply_watermark(image_path: str) -> None:
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


def _to_yaml(obj: dict, indent: int = 0) -> str:
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
            out += f"{pad}{key}:\n{_to_yaml(val, indent + 1)}"
    return out
