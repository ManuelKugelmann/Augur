"""GDELT Cloud API collector."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from ..config.types import Signal

GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"


async def collect_gdelt() -> Signal:
    params = {
        "query": "theme:ECON_BANKRUPTCY OR theme:ENV_CLIMATECHANGE OR theme:CRISISLEX_CRISISLEXREC OR theme:MILITARY",
        "mode": "ArtList",
        "maxrecords": "20",
        "format": "json",
        "sort": "DateDesc",
        "timespan": "24h",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(GDELT_DOC_API, params=params)
        resp.raise_for_status()
        data = resp.json()

    articles = [{
        "title": a.get("title", ""),
        "url": a.get("url", ""),
        "date": a.get("seendate", ""),
        "source": a.get("domain", ""),
        "country": a.get("sourcecountry", ""),
    } for a in data.get("articles", [])]

    return Signal(
        source="gdelt",
        fetched_at=datetime.now(timezone.utc).isoformat(),
        content=articles,
    )
