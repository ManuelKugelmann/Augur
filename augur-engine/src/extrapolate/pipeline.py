"""3-pass LLM extrapolation pipeline."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict
from datetime import datetime, timezone

import httpx

from ..config.types import BrandConfig, HorizonKey, Prediction, Signal
from ..config.horizons import compute_fictive_date
from .prompts import (
    system_prompt_pass1,
    system_prompt_pass2,
    system_prompt_pass3,
    user_prompt_pass1,
)

log = logging.getLogger("augur.extrapolate")

ANTHROPIC_API = "https://api.anthropic.com/v1/messages"


async def _call_claude(system: str, user_content: str, model: str | None = None) -> str:
    """Call Claude API and return text response."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    model = model or os.environ.get("NEWS_MODEL", "claude-sonnet-4-5-20250514")

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            ANTHROPIC_API,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 8000,
                "system": system,
                "messages": [{"role": "user", "content": user_content}],
            },
        )
        resp.raise_for_status()
        data = resp.json()

    text = next(
        (c["text"] for c in data.get("content", []) if c.get("type") == "text"),
        None,
    )
    if not text:
        raise RuntimeError("No text content in Anthropic response")

    usage = data.get("usage", {})
    log.info(
        "tokens: %d in / %d out",
        usage.get("input_tokens", 0),
        usage.get("output_tokens", 0),
    )
    return text


def _extract_json(text: str) -> str:
    """Extract JSON from a response that may contain markdown fences."""
    fenced = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?```", text)
    if fenced:
        return fenced.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text


async def extrapolate(
    brand: BrandConfig,
    horizon: HorizonKey,
    signals: list[Signal],
) -> tuple[Prediction, dict[str, str]]:
    """Run the full 3-pass extrapolation pipeline.

    Returns (prediction, captions_dict).
    """
    fictive_date = compute_fictive_date(horizon)
    signal_data = [{"tool": s.tool, "args": s.arguments, "data": s.result} for s in signals]

    # Pass 1: Signals → prediction
    log.info("pass 1: generating prediction...")
    pass1_raw = await _call_claude(
        system_prompt_pass1(brand),
        user_prompt_pass1(signal_data, horizon, fictive_date, brand.locale),
    )
    pass1 = json.loads(_extract_json(pass1_raw))

    # Pass 2: Rewrite with constructive angle
    log.info("pass 2: editorial rewrite...")
    pass2_raw = await _call_claude(
        system_prompt_pass2(brand.locale),
        json.dumps(pass1, indent=2),
    )
    pass2 = json.loads(_extract_json(pass2_raw))

    # Pass 3: Social captions
    log.info("pass 3: social captions...")
    pass3_raw = await _call_claude(
        system_prompt_pass3(brand.social_targets, brand.locale),
        json.dumps(
            {"headline": pass2["headline"], "signal": pass2["signal"]}, indent=2
        ),
    )
    pass3 = json.loads(_extract_json(pass3_raw))

    now = datetime.now(timezone.utc).isoformat()
    model = os.environ.get("NEWS_MODEL", "claude-sonnet-4-5-20250514")

    prediction = Prediction(
        brand=brand.slug,
        horizon=horizon,
        date_key=fictive_date,
        fictive_date=fictive_date,
        created_at=now,
        headline=pass2["headline"],
        signal=pass2["signal"],
        extrapolation=pass2["extrapolation"],
        in_the_works=pass2["in_the_works"],
        sources=pass2.get("sources", []),
        tags=pass2.get("tags", []),
        model=model,
        image_prompt=pass2.get("image_prompt"),
        sentiment_sector=pass2.get("sentiment_sector"),
        sentiment_direction=pass2.get("sentiment_direction"),
        sentiment_confidence=pass2.get("sentiment_confidence"),
    )

    captions = pass3.get("captions", {})
    return prediction, captions
