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
    "use augur tools to write Jekyll articles, generate images, and queue "
    "social posts. Brands: the (EN general), der (DE general), financial "
    "(EN markets), finanz (DE markets). Horizons: tomorrow, soon, future."
))

log = logging.getLogger("augur")

# ---------------------------------------------------------------------------
# Brand + horizon config (inlined to avoid cross-package imports)
# ---------------------------------------------------------------------------

BRANDS = {
    "the": {
        "name": "The Augur", "locale": "en", "module": "general",
        "masthead": "THE AUGUR",
        "horizons": {"tomorrow": "tomorrow", "soon": "soon", "future": "future"},
        "image_prefix": "Editorial documentary photograph, photojournalistic style, natural lighting, high detail, 35mm lens. ",
        "disclaimer": "AI-generated speculation — not news. Not financial advice.",
    },
    "der": {
        "name": "Der Augur", "locale": "de", "module": "general",
        "masthead": "DER AUGUR",
        "horizons": {"tomorrow": "morgen", "soon": "bald", "future": "zukunft"},
        "image_prefix": "Editorial documentary photograph, photojournalistic style, natural lighting, high detail, 35mm lens. ",
        "disclaimer": "KI-generierte Spekulation — keine Nachricht. Keine Finanzberatung.",
    },
    "financial": {
        "name": "Financial Augur", "locale": "en", "module": "markets",
        "masthead": "FINANCIAL AUGUR",
        "horizons": {"tomorrow": "tomorrow", "soon": "soon", "future": "future"},
        "image_prefix": "Professional financial editorial photograph, Bloomberg terminal aesthetic, corporate environment, clean lighting. ",
        "disclaimer": "AI-generated opinion — not financial advice.",
    },
    "finanz": {
        "name": "Finanz Augur", "locale": "de", "module": "markets",
        "masthead": "FINANZ AUGUR",
        "horizons": {"tomorrow": "morgen", "soon": "bald", "future": "zukunft"},
        "image_prefix": "Professional financial editorial photograph, Bloomberg terminal aesthetic, corporate environment, clean lighting. ",
        "disclaimer": "KI-generierte Einschätzung — keine Finanzberatung.",
    },
}

SECTION_LABELS = {
    "en": {"signal": "The Signal", "extrapolation": "The Extrapolation", "in_the_works": "In The Works"},
    "de": {"signal": "Das Signal", "extrapolation": "Die Extrapolation", "in_the_works": "In Arbeit"},
}


# Per-brand cron schedules: {brand: {horizon: cron_expression}}
# Cron format: "H M" pairs when this brand/horizon should run
SCHEDULES = {
    "the":       {"tomorrow": "0,6,12,18", "soon": "2",  "future": "3/mon"},
    "der":       {"tomorrow": "1,7,13,19", "soon": "4",  "future": "5/mon"},
    "financial": {"tomorrow": "2,8,14,20", "soon": "2",  "future": "6/mon"},
    "finanz":    {"tomorrow": "3,9,15,21", "soon": "4",  "future": "7/mon"},
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


def _slugify(text: str, max_len: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len]


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
    """Check which brand/horizon combos are due for production right now.

    Called by the cron-news agent at each cron tick. Returns a list of
    {brand, horizon} pairs that should be produced this cycle.
    """
    now = datetime.now(timezone.utc)
    due: list[dict] = []

    for brand, horizons in SCHEDULES.items():
        for horizon, schedule in horizons.items():
            if _is_due(schedule, now):
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
    if horizon not in ("tomorrow", "soon", "future"):
        return {"error": "horizon must be: tomorrow, soon, future"}

    b = BRANDS[brand]
    locale = b["locale"]
    horizon_slug = b["horizons"][horizon]
    labels = SECTION_LABELS[locale]
    now = datetime.now(timezone.utc)
    date_key = now.strftime("%Y-%m-%d")
    slug = _slugify(headline)

    # Build front matter
    fm: dict = {
        "layout": "article",
        "brand": brand,
        "horizon": horizon,
        "categories": f"{brand}/{horizon_slug}",
        "date": date_key,
        "headline": headline,
        "fictive_date": date_key,
        "created_at": now.isoformat(),
        "tags": tags,
        "sources": sources,
        "model": os.environ.get("NEWS_MODEL", "claude-sonnet-4-5-20250514"),
        "confidence": confidence,
        "image_prompt": image_prompt,
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
    return {"path": file_path, "brand": brand, "horizon": horizon, "headline": headline}


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
        import asyncio
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


@mcp.tool()
async def queue_social_post(
    brand: str,
    horizon: str,
    platform: str,
    caption: str,
    date_key: str = "",
    image_path: str = "",
) -> dict:
    """Queue a social media post for later publishing.

    Writes a JSON file to the social queue directory.
    """
    date_key = date_key or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    site = _site_dir()
    pending_dir = Path(site) / "_data" / "social" / "pending"
    pending_dir.mkdir(parents=True, exist_ok=True)

    entry = {
        "brand": brand,
        "horizon": horizon,
        "date_key": date_key,
        "platform": platform,
        "caption": caption,
        "image_path": image_path,
        "scheduled_at": datetime.now(timezone.utc).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "post_url": None,
        "retry_count": 0,
        "error": None,
        "posted_at": None,
    }

    filename = f"{brand}-{date_key}-{platform}.json"
    (pending_dir / filename).write_text(json.dumps(entry, indent=2), encoding="utf-8")

    return {"queued": filename}


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
HORIZON_DAYS = {"tomorrow": 2, "soon": 14, "future": 90}


def _parse_front_matter(text: str) -> tuple[dict, str]:
    """Parse YAML front matter from Jekyll markdown. Returns (fm_dict, body)."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("---", 3)
    if end == -1:
        return {}, text
    fm_raw = text[3:end].strip()
    body = text[end + 3:].lstrip("\n")

    fm: dict = {}
    for line in fm_raw.split("\n"):
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if not key or key.startswith("-"):
            continue
        # Parse simple values
        if val == "" or val.lower() == "null":
            fm[key] = None
        elif val.startswith('"') and val.endswith('"'):
            fm[key] = val[1:-1]
        elif val.startswith("["):
            try:
                fm[key] = json.loads(val)
            except json.JSONDecodeError:
                fm[key] = val
        elif val.replace(".", "", 1).isdigit():
            fm[key] = float(val) if "." in val else int(val)
        else:
            fm[key] = val
    return fm, body


def _find_articles(site: str, brand: str = "", horizon: str = "") -> list[Path]:
    """Find all Jekyll post files, optionally filtered by brand/horizon."""
    posts_dir = Path(site) / "_posts"
    if not posts_dir.exists():
        return []
    articles = sorted(posts_dir.rglob("*.md"), reverse=True)
    if not brand and not horizon:
        return articles

    filtered = []
    for path in articles:
        text = path.read_text(encoding="utf-8")
        fm, _ = _parse_front_matter(text)
        if brand and fm.get("brand") != brand:
            continue
        if horizon and fm.get("horizon") != horizon:
            continue
        filtered.append(path)
    return filtered


@mcp.tool()
async def score_prediction(
    article_path: str,
    outcome: str,
    outcome_note: str = "",
) -> dict:
    """Score a prediction article's outcome.

    Updates the front matter outcome fields in the Jekyll markdown file.

    Args:
        article_path: Path to the article .md file (relative to site dir or absolute).
        outcome: One of "confirmed", "partial", "wrong".
        outcome_note: Brief explanation of why this outcome was assigned.
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

    # Replace outcome fields in front matter
    def _replace_field(content: str, field: str, value: str) -> str:
        pattern = re.compile(rf"^({re.escape(field)}:).*$", re.MULTILINE)
        if pattern.search(content):
            return pattern.sub(rf'\1 "{value}"', content)
        # Field missing — insert before closing ---
        end = content.find("---", 3)
        if end != -1:
            return content[:end] + f'{field}: "{value}"\n' + content[end:]
        return content

    text = _replace_field(text, "outcome", outcome)
    text = _replace_field(text, "outcome_date", now_iso)
    if outcome_note:
        text = _replace_field(text, "outcome_note", outcome_note)

    path.write_text(text, encoding="utf-8")
    log.info("scored %s → %s", path.name, outcome)
    return {"path": str(path), "outcome": outcome, "outcome_date": now_iso}


@mcp.tool()
async def list_pending_scores(
    brand: str = "",
    horizon: str = "",
    limit: int = 50,
) -> dict:
    """List prediction articles that are past their horizon date and still unscored.

    These are articles where the prediction window has passed but outcome is still null.
    The LLM agent should research each one and call score_prediction with the result.

    Args:
        brand: Filter by brand slug (optional).
        horizon: Filter by horizon (optional).
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
        fm, _ = _parse_front_matter(text)

        # Skip already scored
        if fm.get("outcome"):
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
        days_needed = HORIZON_DAYS.get(h, 2)
        if (now - pub_date).days < days_needed:
            continue

        pending.append({
            "path": str(path.relative_to(site)),
            "brand": fm.get("brand"),
            "horizon": h,
            "date": str(date_str),
            "headline": fm.get("headline", path.stem),
            "tags": fm.get("tags", []),
            "days_ago": (now - pub_date).days,
        })

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

    # Streak (most recent first, already sorted by path descending)
    current_streak = 0
    streak_type = None
    for s in scored:
        if streak_type is None:
            streak_type = s["outcome"]
            current_streak = 1
        elif s["outcome"] == streak_type:
            current_streak += 1
        else:
            break

    summary = {
        "total": total,
        "confirmed": confirmed,
        "partial": partial,
        "wrong": wrong,
        "accuracy": accuracy,
        "streak": current_streak,
        "streak_type": streak_type,
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
        elif isinstance(val, (int, float)):
            out += f"{pad}{key}: {val}\n"
        elif isinstance(val, bool):
            out += f"{pad}{key}: {'true' if val else 'false'}\n"
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
