"""Type definitions for the Augur pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

BrandKey = Literal["the", "der", "financial", "finanz"]
HorizonKey = Literal["tomorrow", "soon", "future"]
Locale = Literal["en", "de"]
BrandModule = Literal["general", "markets"]
SocialPlatform = Literal["x", "bluesky", "mastodon", "facebook", "linkedin", "instagram"]
OutcomeStatus = Literal["confirmed", "partial", "wrong"] | None


@dataclass
class HorizonConfig:
    key: HorizonKey
    slug: str
    label: str
    refresh_cron: str
    date_offset: str  # "+1d" | "+1m" | "+1y"


@dataclass
class PaletteConfig:
    bg: str
    ink: str
    accent: str
    meta: str


@dataclass
class SourceConfig:
    type: Literal["tavily", "gdelt", "rss", "yahoo", "trade"]
    query: str | None = None
    url: str | None = None


@dataclass
class BrandConfig:
    name: str
    slug: str
    locale: Locale
    module: BrandModule
    masthead: str
    subtitle: str
    horizons: list[HorizonConfig]
    palette: PaletteConfig
    image_style_prefix: str
    tone_prompt: str
    legal_disclaimer: str
    osint_sources: list[SourceConfig]
    social_targets: list[SocialPlatform]
    trade_system_feed: str | None = None


@dataclass
class Signal:
    source: str
    fetched_at: str
    content: object
    query: str | None = None


@dataclass
class Prediction:
    brand: BrandKey
    horizon: HorizonKey
    date_key: str
    fictive_date: str
    created_at: str
    headline: str
    signal: str
    extrapolation: str
    in_the_works: str
    sources: list[dict]
    tags: list[str]
    model: str
    image_prompt: str | None = None
    image_paths: list[str] = field(default_factory=list)
    sentiment_sector: str | None = None
    sentiment_direction: str | None = None
    sentiment_confidence: float | None = None


@dataclass
class SocialQueueEntry:
    brand: BrandKey
    horizon: HorizonKey
    date_key: str
    platform: SocialPlatform
    scheduled_at: str
    caption: str
    image_path: str
    created_at: str
    post_url: str | None = None
    retry_count: int = 0
    error: str | None = None
    posted_at: str | None = None
