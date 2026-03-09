"""Trade system sentiment reader."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from ..config.types import Signal


async def collect_trade_sentiment(path: str | None = None) -> Signal:
    file_path = path or os.environ.get("TRADE_SENTIMENT_PATH", "/tmp/sentiment.json")

    with open(file_path) as f:
        data = json.load(f)

    return Signal(
        source="trade",
        fetched_at=datetime.now(timezone.utc).isoformat(),
        content=data,
    )
