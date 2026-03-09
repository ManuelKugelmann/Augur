"""RSS/Atom feed collector."""

from __future__ import annotations

from datetime import datetime, timezone

import feedparser

from ..config.types import Signal


async def collect_rss(url: str) -> Signal:
    feed = feedparser.parse(url)

    items = [{
        "title": e.get("title", ""),
        "url": e.get("link", ""),
        "snippet": e.get("summary", "")[:300],
        "date": e.get("published", ""),
    } for e in feed.entries[:15]]

    return Signal(
        source="rss",
        fetched_at=datetime.now(timezone.utc).isoformat(),
        query=url,
        content={"feed_title": feed.feed.get("title", ""), "feed_url": url, "items": items},
    )
