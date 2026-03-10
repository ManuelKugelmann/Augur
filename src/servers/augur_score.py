"""Augur scoring MCP server — evaluate past predictions, track accuracy.

Separate from publishing so scoring can run as an independent agent that
researches whether predictions came true, then records verdicts with evidence.
"""

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastmcp import FastMCP

from src.servers.augur_common import (
    HORIZON_DAYS,
    extract_sections,
    find_articles,
    parse_front_matter,
    site_dir,
)

mcp = FastMCP("augur_score", instructions=(
    "Augur scoring agent. Evaluates past predictions that are past their "
    "horizon date. For each pending prediction:\n"
    "1. Read the signal and extrapolation from score_due output\n"
    "2. Use news/finance/data tools to verify whether the prediction came true\n"
    "3. Call score_prediction with outcome (confirmed/partial/wrong), a brief "
    "   outcome_note explaining why, and evidence links from your research\n\n"
    "After scoring all pending items, call generate_scorecard to update "
    "the site's accuracy stats."
))

log = logging.getLogger("augur.score")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def score_due() -> dict:
    """List predictions that are past their horizon and need scoring.

    Called by the cron agent at each tick. Returns pending predictions with
    full context (headline, signal, extrapolation, fictive_date) so the
    agent can research and score them automatically.
    """
    result = await list_pending_scores(limit=10)
    return {
        "score_due": result["count"],
        "pending": result["pending"],
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


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
    site = site_dir()
    articles = find_articles(site, brand, horizon)
    now = datetime.now(timezone.utc)
    pending: list[dict] = []

    for path in articles:
        if len(pending) >= limit:
            break
        text = path.read_text(encoding="utf-8")
        fm, body = parse_front_matter(text)

        current_outcome = fm.get("outcome")
        if current_outcome and not include_scored:
            continue

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

        log_path = path.with_suffix(".scores.json")
        revision = 0
        if log_path.exists():
            try:
                revision = len(json.loads(log_path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, ValueError):
                pass

        sections = extract_sections(body)

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

    site = site_dir()
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
    site = site_dir()
    articles = find_articles(site, brand, horizon)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=last_n_days)

    scored: list[dict] = []
    for path in articles:
        text = path.read_text(encoding="utf-8")
        fm, _ = parse_front_matter(text)
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

    total = len(scored)
    confirmed = sum(1 for s in scored if s["outcome"] == "confirmed")
    partial = sum(1 for s in scored if s["outcome"] == "partial")
    wrong = sum(1 for s in scored if s["outcome"] == "wrong")
    accuracy = round((confirmed + partial * 0.5) / total, 3) if total else 0

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

    data_dir = Path(site) / "_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    scorecard_data = {"generated_at": now.isoformat(), "summary": summary, "breakdown": breakdown}
    (data_dir / "scorecard.json").write_text(json.dumps(scorecard_data, indent=2), encoding="utf-8")

    log.info("scorecard: %d scored, accuracy=%.1f%%", total, accuracy * 100)
    return {"summary": summary, "breakdown": breakdown, "articles": scored}
