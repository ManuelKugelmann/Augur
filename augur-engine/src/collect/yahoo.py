"""Yahoo Finance market data collector."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from ..config.types import Signal

YAHOO_QUOTE_API = "https://query1.finance.yahoo.com/v7/finance/quote"
MARKET_TICKERS = [
    "^GSPC", "^DJI", "^IXIC", "^STOXX50E", "^N225",
    "GC=F", "CL=F", "DX-Y.NYB", "^VIX", "^TNX",
]


async def collect_yahoo() -> Signal:
    symbols = ",".join(MARKET_TICKERS)

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            YAHOO_QUOTE_API,
            params={"symbols": symbols},
            headers={"User-Agent": "augur-engine/0.1"},
        )
        resp.raise_for_status()
        data = resp.json()

    quotes = [{
        "symbol": q.get("symbol"),
        "name": q.get("shortName", q.get("symbol")),
        "price": q.get("regularMarketPrice"),
        "change": q.get("regularMarketChange"),
        "change_pct": q.get("regularMarketChangePercent"),
    } for q in data.get("quoteResponse", {}).get("result", [])]

    return Signal(
        source="yahoo",
        fetched_at=datetime.now(timezone.utc).isoformat(),
        content=quotes,
    )
