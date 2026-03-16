"""Augur publishing MCP server — article creation, image gen, social posting.

Separate from scoring so each can run as an independent agent with
different tool access and scheduling.
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from fastmcp import FastMCP

from augur_common import (
    BRANDS,
    SCHEDULES,
    SECTION_LABELS,
    apply_watermark,
    article_url,
    compute_fictive_date,
    find_articles,
    is_due,
    parse_front_matter,
    site_dir,
    slugify,
    to_yaml,
)

mcp = FastMCP("augur_publish", instructions=(
    "Augur publishing agent. After researching signals via other tools, "
    "use these tools to write Jekyll articles, generate images, create "
    "social cards, post to social media, and push the site. "
    "Bluesky/Mastodon auto-post via API; X/Facebook/LinkedIn/Instagram "
    "send ntfy to admin with deep link.\n\n"
    "Brands: the (EN general), der (DE general), financial (EN markets), "
    "finanz (DE markets). Horizons: tomorrow, soon, future, leap."
))

log = logging.getLogger("augur.publish")


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
async def publish_due() -> dict:
    """Check which brand/horizon combos are due for publishing right now.

    Called by the cron-news agent at each cron tick. Returns a list of
    {brand, horizon} pairs that should be produced this cycle.
    """
    now = datetime.now(timezone.utc)
    due: list[dict] = []

    for brand, horizons in SCHEDULES.items():
        for horizon, schedule in horizons.items():
            if is_due(schedule, now):
                due.append({"brand": brand, "horizon": horizon})

    return {"due": due, "checked_at": now.isoformat(), "count": len(due)}


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

    # Dedup: check if an article for this brand/horizon already exists today
    site = site_dir()
    existing = find_articles(site, brand, horizon_slug)
    for art_path in existing:
        if art_path.name.startswith(date_key):
            return {"error": f"Article already published today: {art_path.name}",
                    "existing_path": str(art_path)}
    fictive_date = compute_fictive_date(horizon, now)
    slug = slugify(headline)
    url = article_url(brand, horizon_slug, fictive_date)

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

    yaml = to_yaml(fm)
    body = f"""## {labels['signal']}

{signal}

## {labels['extrapolation']}

{extrapolation}

## {labels['in_the_works']}

{in_the_works}
"""
    markdown = f"---\n{yaml}---\n\n{body}"

    site = site_dir()
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
    site = site_dir()
    image_prefix = f"{brand}-{horizon}-{date_key}"
    image_path = os.path.join(site, "assets", "images", f"{image_prefix}.webp")

    try:
        import asyncio

        import httpx
        token = os.environ.get("REPLICATE_API_TOKEN")
        if not token:
            return {"error": "REPLICATE_API_TOKEN not set"}

        auth_headers = {"Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                "https://api.replicate.com/v1/models/black-forest-labs/flux-2-klein-4b/predictions",
                headers={**auth_headers, "Content-Type": "application/json"},
                json={"input": {
                    "prompt": full_prompt, "width": 1024, "height": 768,
                    "num_outputs": 1, "output_format": "webp", "output_quality": 85,
                }},
            )
            resp.raise_for_status()
            prediction = resp.json()

            poll_url = prediction.get("urls", {}).get(
                "get", f"https://api.replicate.com/v1/predictions/{prediction['id']}"
            )
            for _ in range(60):
                if prediction["status"] in ("succeeded", "failed"):
                    break
                await asyncio.sleep(1)
                r = await client.get(poll_url, headers=auth_headers)
                r.raise_for_status()
                prediction = r.json()

            if prediction["status"] == "failed":
                return {"error": f"Image generation failed: {prediction.get('error')}"}

            image_url = prediction.get("output", [None])[0]
            if not image_url:
                return {"error": "No image URL in output"}

            r = await client.get(image_url)
            r.raise_for_status()
            Path(image_path).parent.mkdir(parents=True, exist_ok=True)
            Path(image_path).write_bytes(r.content)

        try:
            from PIL import Image, ImageDraw, ImageFont
            apply_watermark(image_path)
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

    site = site_dir()
    out_dir = os.path.join(site, "assets", "cards", brand, horizon)
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    slug = slugify(headline, 30)
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


# ---------------------------------------------------------------------------
# Social posting
# ---------------------------------------------------------------------------

_AUTO_PLATFORMS = {"bluesky", "mastodon"}
_MANUAL_PLATFORMS = {"x", "facebook", "linkedin", "instagram"}


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
        r = await client.post(f"{pds}/xrpc/com.atproto.server.createSession",
                              json={"identifier": handle, "password": password})
        r.raise_for_status()
        session = r.json()
        token = session["accessJwt"]
        did = session["did"]
        auth_headers = {"Authorization": f"Bearer {token}"}

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

    ntfy_base = os.environ.get("NTFY_BASE_URL", "https://ntfy.sh")
    ntfy_topic = os.environ.get("NTFY_TOPIC", "")
    if not ntfy_topic:
        return {"error": "NTFY_TOPIC not set — cannot notify admin"}

    b = BRANDS.get(brand, {})
    brand_name = b.get("name", brand)
    title = f"Post to {platform.title()} — {brand_name}"
    body = f"{caption}\n\n{article_url}"

    def _sanitize_header(v: str) -> str:
        return v.replace("\r", "").replace("\n", " ")

    headers = {
        "Title": _sanitize_header(title),
        "Priority": "default",
        "Tags": f"mega,{platform}",
        "Click": article_url,
        "Actions": f"view, Open article, {article_url}",
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{ntfy_base}/{ntfy_topic}",
                                  content=body, headers=headers)
            r.raise_for_status()
        return {"notified": True, "platform": platform, "topic": ntfy_topic}
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
    site = site_dir()
    branch = os.environ.get("AUGUR_SITE_BRANCH", "augur_news")

    async def _run(cmd: list[str]) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=site,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode or 0, stdout.decode(), stderr.decode()

    rc, _, stderr = await _run(["git", "add", "_posts/", "assets/", "_data/"])
    if rc != 0:
        return {"error": f"git add failed: {stderr}"}

    rc, status_out, _ = await _run(["git", "status", "--porcelain"])
    if not status_out.strip():
        return {"status": "no changes to push"}

    commit_msg = message or f"augur: new predictions {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
    rc, _, stderr = await _run(["git", "commit", "-m", commit_msg])
    if rc != 0:
        return {"error": f"git commit failed: {stderr}"}

    for attempt in range(5):
        rc, _, stderr = await _run(["git", "push", "-u", "origin", branch])
        if rc == 0:
            return {"status": "pushed", "branch": branch}
        if attempt < 4:
            await asyncio.sleep(2 ** (attempt + 1))

    return {"error": f"push failed after 5 attempts: {stderr}"}
