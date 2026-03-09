"""Tavily news search API collector."""

from __future__ import annotations

import os
from datetime import datetime, timezone

import httpx

from ..config.types import Signal

TAVILY_API = "https://api.tavily.com/search"


async def collect_tavily(query: str) -> Signal:
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY not set")

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(TAVILY_API, json={
            "api_key": api_key,
            "query": query,
            "search_depth": "advanced",
            "max_results": 10,
            "include_answer": False,
            "include_raw_content": False,
        })
        resp.raise_for_status()
        data = resp.json()

    return Signal(
        source="tavily",
        fetched_at=datetime.now(timezone.utc).isoformat(),
        query=query,
        content=[{
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": r.get("content", ""),
            "score": r.get("score", 0),
            "date": r.get("published_date"),
        } for r in data.get("results", [])],
    )
