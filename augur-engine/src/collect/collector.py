"""Signal collector orchestrator."""

from __future__ import annotations

import asyncio
import logging

from ..config.types import Signal, SourceConfig
from .tavily import collect_tavily
from .rss import collect_rss
from .gdelt import collect_gdelt
from .yahoo import collect_yahoo
from .trade_sentiment import collect_trade_sentiment

log = logging.getLogger("augur.collect")

MIN_SIGNALS = 1


async def _collect_one(src: SourceConfig) -> Signal:
    match src.type:
        case "tavily":
            return await collect_tavily(src.query or "top global developments today")
        case "rss":
            return await collect_rss(src.url or "")
        case "gdelt":
            return await collect_gdelt()
        case "yahoo":
            return await collect_yahoo()
        case "trade":
            return await collect_trade_sentiment()
        case _:
            raise ValueError(f"Unknown source type: {src.type}")


async def collect_signals(sources: list[SourceConfig]) -> list[Signal]:
    """Collect signals from all configured sources, tolerating individual failures."""
    results: list[Signal] = []
    errors: list[str] = []

    tasks = [_collect_one(src) for src in sources]
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)

    for src, outcome in zip(sources, outcomes):
        if isinstance(outcome, BaseException):
            errors.append(src.type)
            log.warning("collect %s failed: %s", src.type, outcome)
        else:
            results.append(outcome)

    log.info("collect: %d/%d sources succeeded", len(results), len(sources))
    if errors:
        log.warning("collect: failed sources: %s", ", ".join(errors))

    return results
