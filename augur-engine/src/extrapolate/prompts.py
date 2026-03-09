"""Prompt templates for the 3-pass LLM pipeline."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from ..config.types import BrandConfig, HorizonKey, Locale
from ..config.horizons import SECTION_LABELS


def system_prompt_pass1(brand: BrandConfig) -> str:
    """Build system prompt for Pass 1: signal → extrapolation."""
    labels = SECTION_LABELS[brand.locale]
    sentiment_block = ""
    if brand.module == "markets":
        sentiment_block = """,
  "sentiment_sector": "string — sector name",
  "sentiment_direction": "bullish | bearish | neutral",
  "sentiment_confidence": 0.0-1.0"""

    lang_rule = (
        "Write in German (Hochdeutsch)"
        if brand.locale == "de"
        else "Write in English, AP/Reuters style"
    )

    return f"""{brand.tone_prompt}

You produce structured predictions for {brand.name}. Each prediction has three sections:

1. "{labels['signal']}" — What's actually happening right now. Factual, uncomfortable, sourced. Cite specific data points from the provided signals.

2. "{labels['extrapolation']}" — Where this leads if unchecked. A wake-up call, not sensationalism. Be specific about timeframes and consequences.

3. "{labels['in_the_works']}" — Who's working on solutions. Real efforts, named, sourced — not hopium. If no credible solution exists, say so.

Rules:
- Never fabricate statistics or data points
- Cite the actual signals provided
- {lang_rule}
- Be specific, not vague
- Every claim must trace back to a provided signal or widely known fact

Output MUST be valid JSON matching this schema:
{{
  "headline": "string — compelling, specific, max 100 chars",
  "signal": "string — markdown for The Signal section",
  "extrapolation": "string — markdown for The Extrapolation section",
  "in_the_works": "string — markdown for In The Works section",
  "sources": [{{"title": "string", "url": "string or null"}}],
  "tags": ["string — 3-6 lowercase tags"],
  "image_prompt": "string — scene description for AI image generation, photojournalistic style",
  "confidence": "high | medium | low"{sentiment_block}
}}"""


def user_prompt_pass1(
    signals: list[object],
    horizon: HorizonKey,
    fictive_date: str,
    locale: Locale,
) -> str:
    """Build user prompt for Pass 1 with collected signals."""
    horizon_labels = {
        "en": {
            "tomorrow": "Tomorrow",
            "soon": "Soon (1 month)",
            "future": "Future (1 year)",
        },
        "de": {
            "tomorrow": "Morgen",
            "soon": "Bald (1 Monat)",
            "future": "Zukunft (1 Jahr)",
        },
    }
    label = horizon_labels[locale][horizon]
    now = datetime.now(timezone.utc).isoformat()

    return f"""Horizon: {label}
Fictive prediction date: {fictive_date}
Generated: {now}

Below are today's collected signals from multiple sources. Analyze them and produce ONE prediction article as JSON.

---SIGNALS---
{json.dumps(signals, indent=2, default=str)}
---END SIGNALS---

Produce the prediction JSON now. Focus on the most significant development across these signals."""


def system_prompt_pass2(locale: Locale) -> str:
    """Build system prompt for Pass 2: rewrite with constructive angle."""
    lang = "German" if locale == "de" else "English"
    return f"""You are an editor. You receive a prediction article as JSON. Your job:

1. Keep "signal" section unchanged — it must stay factual and uncomfortable
2. Strengthen "in_the_works" section — find the genuinely constructive thread, add specificity
3. Ensure "extrapolation" is a wake-up call, not doom — it should motivate, not paralyze
4. Polish headline for maximum impact
5. Keep all data points and sources intact

Language: {lang}

Output the full JSON with the same schema, modified as needed."""


def system_prompt_pass3(platforms: list[str], locale: Locale) -> str:
    """Build system prompt for Pass 3: generate social captions."""
    platform_entries = ",\n    ".join(
        f'"{p}": "string — platform-native caption"' for p in platforms
    )
    lang = "German" if locale == "de" else "English"

    return f"""You generate social media captions for a prediction article. Output JSON:

{{
  "captions": {{
    {platform_entries}
  }}
}}

Platform tone guidelines:
- x: Punchy, provocative, emoji-light, max 280 chars
- bluesky: Like X but more earnest
- mastodon: Like X but more earnest, hashtags welcome
- facebook: Question-format hook, longer text ok
- linkedin: Professional framing, data-forward
- instagram: Descriptive, emoji-heavy, hashtag block

Language: {lang}
Every caption MUST include: "AI-generated prediction" disclaimer.
Every caption MUST end with a placeholder: [LINK]"""
