"""Price ingestion — fetch OHLCV, compute indicators, store snapshots.

Decoupled bridge between the ta server (Yahoo Finance + indicator math)
and the signals store (MongoDB snapshots).  Designed to run from cron
(``augur cron``) or standalone (``python -m src.ingest.price_ingest``).

Flow per ticker:
  1. Fetch OHLCV from Yahoo Finance (reuses indicators_server logic)
  2. Compute composite indicators (SMA, RSI, MACD, Bollinger)
  3. Store OHLCV latest bar as snapshot (type=price)
  4. Store indicator results as snapshot (type=indicators)
  5. Emit event if composite signal changed since last snapshot
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("augur.ingest.price")

# ── Kinds whose profile IDs are Yahoo-compatible tickers ──
TICKER_KINDS = ("stocks", "etfs", "crypto", "indices")

# Yahoo Finance ticker suffixes for special kinds
_YAHOO_SUFFIX: dict[str, str] = {
    "crypto": "-USD",  # BTC → BTC-USD
}

# Mapping from profile kind to Yahoo-style ticker prefix for indices
_INDEX_PREFIX: dict[str, str] = {
    "indices": "^",  # SPX → ^SPX
}


def _to_yahoo_ticker(entity_id: str, kind: str) -> str:
    """Convert a profile entity ID to a Yahoo Finance ticker symbol."""
    suffix = _YAHOO_SUFFIX.get(kind, "")
    prefix = _INDEX_PREFIX.get(kind, "")
    return f"{prefix}{entity_id}{suffix}"


def _latest_snapshot_data(kind: str, entity: str, snap_type: str,
                          store_mod) -> dict | None:
    """Fetch the most recent snapshot of a given type for an entity."""
    rows = store_mod.history(kind, entity, type=snap_type, limit=1)
    if rows and not isinstance(rows[0], dict):
        return None
    if rows and "error" not in rows[0]:
        return rows[0].get("data", {})
    return None


async def ingest_ticker(
    entity_id: str,
    kind: str,
    indicators_mod,
    store_mod,
    *,
    period: str = "1y",
) -> dict:
    """Fetch prices + indicators for one ticker and store as snapshots.

    Returns a summary dict with status and any signal change.
    """
    yahoo_ticker = _to_yahoo_ticker(entity_id, kind)

    # 1. Fetch OHLCV
    prices = await indicators_mod._fetch_yahoo_ohlcv(yahoo_ticker, period)
    if "error" in prices:
        log.warning("fetch failed %s/%s: %s", kind, entity_id, prices["error"])
        return {"entity": entity_id, "kind": kind, "status": "fetch_error",
                "error": prices["error"]}

    df = prices["df"]
    currency = prices["currency"]

    # 2. Store latest OHLCV bar as price snapshot
    last_bar = df.iloc[-1]
    price_data = {
        "open": round(float(last_bar["open"]), 4) if last_bar["open"] is not None else None,
        "high": round(float(last_bar["high"]), 4) if last_bar["high"] is not None else None,
        "low": round(float(last_bar["low"]), 4) if last_bar["low"] is not None else None,
        "close": round(float(last_bar["close"]), 4),
        "volume": int(last_bar["volume"]) if last_bar["volume"] is not None else None,
        "currency": currency,
        "date": df.index[-1].strftime("%Y-%m-%d"),
    }
    store_mod.snapshot(kind, entity_id, "price", price_data,
                       source="yahoo_finance")

    # 3. Compute full indicators
    indicator_result = await indicators_mod.analyze_full(yahoo_ticker, period)
    if "error" in indicator_result:
        log.warning("indicators failed %s/%s: %s",
                    kind, entity_id, indicator_result["error"])
        return {"entity": entity_id, "kind": kind, "status": "indicators_error",
                "error": indicator_result["error"]}

    # 4. Store indicators snapshot
    store_mod.snapshot(kind, entity_id, "indicators", indicator_result,
                       source="yahoo_finance")

    # 5. Check for signal change → emit event
    signal_change = None
    new_composite = indicator_result.get("composite", "")
    if new_composite:
        prev = _latest_snapshot_data(kind, entity_id, "indicators", store_mod)
        # prev is the one we just stored; get the one before that
        rows = store_mod.history(kind, entity_id, type="indicators", limit=2)
        old_composite = ""
        if len(rows) >= 2 and "data" in rows[1]:
            old_composite = rows[1]["data"].get("composite", "")
        if old_composite and old_composite != new_composite:
            signal_change = {"from": old_composite, "to": new_composite}
            severity = "high" if new_composite in ("strong_buy", "avoid") else "medium"
            store_mod.event(
                subtype="signal_change",
                summary=(f"{entity_id} composite signal changed: "
                         f"{old_composite} → {new_composite}"),
                data={
                    "entity": entity_id,
                    "kind": kind,
                    "old_signal": old_composite,
                    "new_signal": new_composite,
                    "close": price_data["close"],
                    "rsi_14": indicator_result.get("rsi_14"),
                    "trend_signal": indicator_result.get("trend_signal"),
                },
                severity=severity,
                entities=[entity_id],
                source="price_ingest",
            )
            log.info("signal change %s/%s: %s → %s",
                     kind, entity_id, old_composite, new_composite)

    return {
        "entity": entity_id,
        "kind": kind,
        "status": "ok",
        "close": price_data["close"],
        "composite": new_composite or None,
        "signal_change": signal_change,
    }


async def ingest_kind(
    kind: str,
    indicators_mod,
    store_mod,
    *,
    entity_ids: list[str] | None = None,
    period: str = "1y",
    delay: float = 1.0,
) -> list[dict]:
    """Ingest prices for all profiled entities of a kind.

    If entity_ids is None, reads the list from store profiles.
    Adds a delay between tickers to avoid Yahoo rate-limiting.
    """
    if entity_ids is None:
        profiles = store_mod.list_profiles(kind)
        entity_ids = [p["id"] for p in profiles]

    if not entity_ids:
        log.info("no entities for kind=%s, skipping", kind)
        return []

    results = []
    for i, eid in enumerate(entity_ids):
        result = await ingest_ticker(eid, kind, indicators_mod, store_mod,
                                     period=period)
        results.append(result)
        ok = result["status"] == "ok"
        log.info("[%d/%d] %s/%s: %s%s", i + 1, len(entity_ids), kind, eid,
                 result["status"],
                 f" close={result.get('close')}" if ok else "")
        # Rate limit: sleep between requests (except after last)
        if delay > 0 and i < len(entity_ids) - 1:
            await asyncio.sleep(delay)

    return results


async def run_ingest(
    indicators_mod,
    store_mod,
    *,
    kinds: list[str] | None = None,
    period: str = "1y",
    delay: float = 1.0,
) -> dict:
    """Run price ingestion for all ticker-based kinds.

    Returns summary with per-kind results.
    """
    if kinds is None:
        kinds = list(TICKER_KINDS)

    ts_start = datetime.now(timezone.utc)
    summary: dict = {"ts": ts_start.isoformat(), "kinds": {}}

    for kind in kinds:
        if kind not in TICKER_KINDS:
            log.warning("skipping non-ticker kind: %s", kind)
            continue
        results = await ingest_kind(kind, indicators_mod, store_mod,
                                    period=period, delay=delay)
        ok = sum(1 for r in results if r["status"] == "ok")
        errors = sum(1 for r in results if r["status"] != "ok")
        changes = [r for r in results if r.get("signal_change")]
        summary["kinds"][kind] = {
            "total": len(results),
            "ok": ok,
            "errors": errors,
            "signal_changes": len(changes),
        }
        log.info("kind=%s: %d ok, %d errors, %d signal changes",
                 kind, ok, errors, len(changes))

    elapsed = (datetime.now(timezone.utc) - ts_start).total_seconds()
    summary["elapsed_seconds"] = round(elapsed, 1)
    return summary


# ── CLI entry point ──────────────────────────────────

def main():
    """Run price ingestion from command line or cron."""
    logging.basicConfig(
        level=logging.INFO,
        format="[augur-cron] ingest: %(message)s",
    )

    # Add source paths
    root = Path(__file__).resolve().parent.parent.parent
    sys.path.insert(0, str(root / "src" / "servers"))
    sys.path.insert(0, str(root / "src" / "store"))

    # Load env
    try:
        from dotenv import load_dotenv
        load_dotenv(root / ".env")
    except ImportError:
        pass

    import indicators_server as indicators_mod
    import server as store_mod

    # Parse optional kind filter from argv
    kinds = None
    if len(sys.argv) > 1:
        kinds = sys.argv[1].split(",")

    result = asyncio.run(run_ingest(indicators_mod, store_mod, kinds=kinds))
    for kind, stats in result.get("kinds", {}).items():
        print(f"[augur-cron] ingest {kind}: "
              f"{stats['ok']}/{stats['total']} ok, "
              f"{stats['signal_changes']} signal changes")
    print(f"[augur-cron] ingest done in {result.get('elapsed_seconds', '?')}s")


if __name__ == "__main__":
    main()
