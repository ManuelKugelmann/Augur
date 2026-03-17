"""Tests for price_ingest — decoupled OHLCV fetch → store pipeline.

Mocks both the indicators server (Yahoo fetch + analysis) and the store
(snapshot/event/history/list_profiles), so no network or MongoDB needed.
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest

# Add ingest dir to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "ingest"))
import price_ingest as pi  # noqa: E402


# ── Helpers ──────────────────────────────────────────


def _make_mock_yahoo_df(n=250, start=100.0, trend=0.2):
    """Build a mock pandas DataFrame matching _fetch_yahoo_ohlcv output."""
    pd = pytest.importorskip("pandas")
    from datetime import datetime, timezone, timedelta
    import time
    base_ts = int(time.time()) - n * 86400
    closes = [start + i * trend for i in range(n)]
    index = [datetime.fromtimestamp(base_ts + i * 86400, tz=timezone.utc) for i in range(n)]
    return pd.DataFrame({
        "open": [c - 0.5 for c in closes],
        "high": [c + 1.0 for c in closes],
        "low": [c - 1.0 for c in closes],
        "close": closes,
        "volume": [1_000_000] * n,
    }, index=index)


def _make_indicators_mod(df=None, analysis_result=None, fetch_error=None):
    """Create a mock indicators module."""
    mod = SimpleNamespace()

    async def _fetch_yahoo_ohlcv(ticker, period="1y", interval="1d"):
        if fetch_error:
            return {"error": fetch_error}
        return {"df": df or _make_mock_yahoo_df(), "ticker": ticker.upper(),
                "currency": "USD"}

    async def analyze_full(ticker, period="1y"):
        if fetch_error:
            return {"error": fetch_error}
        if analysis_result:
            return dict(analysis_result)
        return {
            "ticker": ticker.upper(),
            "currency": "USD",
            "current_close": 150.0,
            "sma_200": 140.0,
            "trend_signal": "bullish",
            "rsi_14": 55.2,
            "rsi_signal": "neutral",
            "composite": "hold",
            "advice": "Trend bullish, RSI neutral — hold or wait.",
        }

    mod._fetch_yahoo_ohlcv = _fetch_yahoo_ohlcv
    mod.analyze_full = analyze_full
    return mod


def _make_store_mod(existing_snapshots=None):
    """Create a mock store module that records calls."""
    mod = SimpleNamespace()
    mod._snapshots = []
    mod._events = []

    def snapshot(kind, entity, type, data, region="", source="", ts="",
                 lon=None, lat=None):
        mod._snapshots.append({
            "kind": kind, "entity": entity, "type": type,
            "data": data, "source": source,
        })
        return {"id": f"mock_{len(mod._snapshots)}", "status": "ok"}

    def event(subtype, summary, data, severity="medium", countries=None,
              entities=None, region="", source="", ts="", lon=None, lat=None):
        mod._events.append({
            "subtype": subtype, "summary": summary, "data": data,
            "severity": severity, "entities": entities,
        })
        return {"id": "mock_event", "status": "ok"}

    def history(kind, entity, type="", region="", after="", before="",
                limit=100):
        if existing_snapshots:
            return existing_snapshots[:limit]
        # Return the snapshots we've stored so far (for signal change detection)
        matching = [s for s in mod._snapshots
                    if s["kind"] == kind and s["entity"] == entity
                    and (not type or s["type"] == type)]
        return [{"data": s["data"]} for s in reversed(matching)][:limit]

    def list_profiles(kind, region="", limit=500):
        if kind == "stocks":
            return [
                {"id": "AAPL", "name": "Apple Inc.", "region": "global"},
                {"id": "NVDA", "name": "NVIDIA Corp.", "region": "global"},
            ]
        if kind == "etfs":
            return [{"id": "SPY", "name": "SPDR S&P 500", "region": "global"}]
        return []

    mod.snapshot = snapshot
    mod.event = event
    mod.history = history
    mod.list_profiles = list_profiles
    return mod


# ── Tests ────────────────────────────────────────────


class TestToYahooTicker:
    def test_stock_passthrough(self):
        assert pi._to_yahoo_ticker("AAPL", "stocks") == "AAPL"

    def test_etf_passthrough(self):
        assert pi._to_yahoo_ticker("SPY", "etfs") == "SPY"

    def test_crypto_suffix(self):
        assert pi._to_yahoo_ticker("BTC", "crypto") == "BTC-USD"
        assert pi._to_yahoo_ticker("ETH", "crypto") == "ETH-USD"

    def test_index_prefix(self):
        assert pi._to_yahoo_ticker("SPX", "indices") == "^SPX"
        assert pi._to_yahoo_ticker("GSPC", "indices") == "^GSPC"


class TestIngestTicker:
    def test_successful_ingest(self):
        ind = _make_indicators_mod()
        store = _make_store_mod()
        result = asyncio.run(pi.ingest_ticker("AAPL", "stocks", ind, store))

        assert result["status"] == "ok"
        assert result["entity"] == "AAPL"
        assert result["kind"] == "stocks"
        assert result["close"] is not None
        assert result["composite"] == "hold"
        assert result["signal_change"] is None

        # Should have stored 2 snapshots: price + indicators
        assert len(store._snapshots) == 2
        assert store._snapshots[0]["type"] == "price"
        assert store._snapshots[0]["source"] == "yahoo_finance"
        assert store._snapshots[1]["type"] == "indicators"

        # Price snapshot should have OHLCV fields
        price_data = store._snapshots[0]["data"]
        assert "open" in price_data
        assert "high" in price_data
        assert "low" in price_data
        assert "close" in price_data
        assert "volume" in price_data
        assert "currency" in price_data

    def test_fetch_error(self):
        ind = _make_indicators_mod(fetch_error="HTTP 429")
        store = _make_store_mod()
        result = asyncio.run(pi.ingest_ticker("AAPL", "stocks", ind, store))

        assert result["status"] == "fetch_error"
        assert "429" in result["error"]
        assert len(store._snapshots) == 0

    def test_signal_change_emits_event(self):
        """When composite signal changes, an event should be emitted."""
        # Existing snapshot has "avoid" — fetched BEFORE new snapshot is stored
        existing = [
            {"data": {"composite": "avoid"}},  # previous (most recent before new ingest)
        ]
        ind = _make_indicators_mod()
        store = _make_store_mod(existing_snapshots=existing)
        result = asyncio.run(pi.ingest_ticker("AAPL", "stocks", ind, store))

        assert result["status"] == "ok"
        assert result["signal_change"] == {"from": "avoid", "to": "hold"}

        # Should have emitted a signal_change event
        assert len(store._events) == 1
        evt = store._events[0]
        assert evt["subtype"] == "signal_change"
        assert "AAPL" in evt["summary"]
        assert evt["data"]["old_signal"] == "avoid"
        assert evt["data"]["new_signal"] == "hold"
        assert evt["entities"] == ["AAPL"]

    def test_signal_change_high_severity_for_strong_buy(self):
        """strong_buy and avoid signals should get high severity."""
        existing = [
            {"data": {"composite": "hold"}},  # previous signal (fetched before new store)
        ]
        analysis = {
            "ticker": "AAPL", "currency": "USD", "current_close": 150.0,
            "composite": "strong_buy", "trend_signal": "bullish",
            "rsi_14": 25.0,
        }
        ind = _make_indicators_mod(analysis_result=analysis)
        store = _make_store_mod(existing_snapshots=existing)
        result = asyncio.run(pi.ingest_ticker("AAPL", "stocks", ind, store))

        assert len(store._events) == 1
        assert store._events[0]["severity"] == "high"

    def test_no_event_when_signal_unchanged(self):
        """No event when composite stays the same."""
        existing = [
            {"data": {"composite": "hold"}},  # previous signal matches new "hold"
        ]
        ind = _make_indicators_mod()
        store = _make_store_mod(existing_snapshots=existing)
        result = asyncio.run(pi.ingest_ticker("AAPL", "stocks", ind, store))

        assert result["signal_change"] is None
        assert len(store._events) == 0

    def test_crypto_ticker_conversion(self):
        """Crypto tickers should get -USD suffix for Yahoo."""
        ind = _make_indicators_mod()
        store = _make_store_mod()
        result = asyncio.run(pi.ingest_ticker("BTC", "crypto", ind, store))

        assert result["status"] == "ok"
        # Indicators snapshot should have the Yahoo ticker
        ind_data = store._snapshots[1]["data"]
        assert ind_data["ticker"] == "BTC-USD"


class TestIngestKind:
    def test_ingests_all_profiles(self):
        ind = _make_indicators_mod()
        store = _make_store_mod()
        results = asyncio.run(
            pi.ingest_kind("stocks", ind, store, delay=0)
        )

        # list_profiles returns AAPL and NVDA
        assert len(results) == 2
        assert all(r["status"] == "ok" for r in results)
        # 2 tickers x 2 snapshots each = 4 snapshots
        assert len(store._snapshots) == 4

    def test_explicit_entity_ids(self):
        ind = _make_indicators_mod()
        store = _make_store_mod()
        results = asyncio.run(
            pi.ingest_kind("stocks", ind, store,
                           entity_ids=["MSFT"], delay=0)
        )
        assert len(results) == 1
        assert results[0]["entity"] == "MSFT"

    def test_empty_kind_skipped(self):
        ind = _make_indicators_mod()
        store = _make_store_mod()
        results = asyncio.run(
            pi.ingest_kind("crypto", ind, store, delay=0)
        )
        # list_profiles returns [] for crypto
        assert results == []


class TestRunIngest:
    def test_full_run(self):
        ind = _make_indicators_mod()
        store = _make_store_mod()
        summary = asyncio.run(
            pi.run_ingest(ind, store, kinds=["stocks", "etfs"], delay=0)
        )

        assert "ts" in summary
        assert "elapsed_seconds" in summary
        assert summary["kinds"]["stocks"]["total"] == 2
        assert summary["kinds"]["stocks"]["ok"] == 2
        assert summary["kinds"]["etfs"]["total"] == 1
        assert summary["kinds"]["etfs"]["ok"] == 1

    def test_invalid_kind_skipped(self):
        ind = _make_indicators_mod()
        store = _make_store_mod()
        summary = asyncio.run(
            pi.run_ingest(ind, store, kinds=["commodities"], delay=0)
        )
        # commodities is not in TICKER_KINDS
        assert "commodities" not in summary["kinds"]

    def test_default_kinds(self):
        assert set(pi.TICKER_KINDS) == {"stocks", "etfs", "crypto", "indices"}
