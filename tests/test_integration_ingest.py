"""Integration tests for the price ingestion + alerts pipeline against real APIs.

Tests the full flow: Yahoo Finance → price_ingest → store (Atlas) → hooks.
Requires:
  - MONGO_URI_SIGNALS pointing to a live MongoDB instance
  - Network access to Yahoo Finance (no API key needed)
  - ta + httpx + pandas installed

Marked @pytest.mark.integration — excluded from normal CI,
runs in the `integration-store` job.
"""
import asyncio
import importlib
import os
import sys
from pathlib import Path

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required")
pd = pytest.importorskip("pandas", reason="pandas required")
pytest.importorskip(
    "ta", reason="ta library required (SETUPTOOLS_USE_DISTUTILS=stdlib pip install ta --no-build-isolation)"
)

MONGO_URI = os.environ.get("MONGO_URI_SIGNALS", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not MONGO_URI, reason="MONGO_URI_SIGNALS not set"),
]

ROOT = Path(__file__).resolve().parent.parent


def _check_mongo():
    try:
        import pymongo
        client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")
        client.close()
    except Exception as exc:
        pytest.skip(f"MongoDB not reachable: {exc}")


def _ensure_real_pymongo():
    if "pymongo" in sys.modules and hasattr(sys.modules["pymongo"], "_mock_name"):
        del sys.modules["pymongo"]
    import pymongo  # noqa: F401


def _fresh_store(tmp_path):
    """Import store module with real pymongo, pointing at real Atlas."""
    profiles = tmp_path / "profiles" / "global" / "stocks"
    profiles.mkdir(parents=True)

    os.environ["PROFILES_DIR"] = str(tmp_path / "profiles")
    os.environ.setdefault("MONGO_URI_SIGNALS", MONGO_URI)

    _ensure_real_pymongo()

    store_dir = str(ROOT / "src" / "store")
    alerts_dir = str(ROOT / "src" / "alerts")
    for d in (store_dir, alerts_dir):
        if d not in sys.path:
            sys.path.insert(0, d)

    # Force-reimport
    for mod_name in list(sys.modules):
        if mod_name in ("server", "threshold_checker", "impact_mapper"):
            del sys.modules[mod_name]

    import server
    server._client = None
    server._cols_ready = set()
    server._hooks_loaded = False
    # Clear any previously loaded hooks
    for key in ("_threshold_checker", "_impact_mapper"):
        server.__dict__.pop(key, None)
    return server


def _fresh_indicators():
    """Import indicators module with real httpx."""
    servers_dir = str(ROOT / "src" / "servers")
    if servers_dir not in sys.path:
        sys.path.insert(0, servers_dir)

    if "indicators_server" in sys.modules:
        del sys.modules["indicators_server"]

    import indicators_server
    return indicators_server


def _fresh_price_ingest():
    """Import price_ingest module."""
    ingest_dir = str(ROOT / "src" / "ingest")
    if ingest_dir not in sys.path:
        sys.path.insert(0, ingest_dir)

    if "price_ingest" in sys.modules:
        del sys.modules["price_ingest"]

    import price_ingest
    return price_ingest


def _cleanup_db(store):
    """Drop test collections."""
    try:
        db = store._db()
        for name in db.list_collection_names():
            if (name.startswith("snap_") or name.startswith("arch_")
                    or name.startswith("profiles_") or name == "events"
                    or name in ("user_notes", "shared_notes")):
                db.drop_collection(name)
    except Exception:
        pass
    store._client = None
    store._cols_ready = set()
    store._hooks_loaded = False


# ── Tests ────────────────────────────────────────────


class TestIngestSingleTicker:
    """Ingest a real ticker (AAPL) via Yahoo Finance and verify snapshots in Atlas."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        _check_mongo()
        self.store = _fresh_store(tmp_path)
        self.indicators = _fresh_indicators()
        self.pi = _fresh_price_ingest()
        yield
        _cleanup_db(self.store)

    def test_ingest_aapl_stores_price_and_indicators(self):
        """Full round-trip: Yahoo → compute → store → verify."""
        result = asyncio.run(
            self.pi.ingest_ticker("AAPL", "stocks", self.indicators, self.store)
        )

        assert result["status"] == "ok", f"ingest failed: {result}"
        assert result["entity"] == "AAPL"
        assert result["close"] is not None
        assert isinstance(result["close"], (int, float))

        # Verify price snapshot in Atlas
        price_hist = self.store.history(kind="stocks", entity="AAPL", type="price")
        assert len(price_hist) >= 1, "no price snapshot stored"
        price_data = price_hist[0].get("data", {})
        assert "close" in price_data
        assert "volume" in price_data
        assert "currency" in price_data
        assert price_data["currency"] == "USD"

        # Verify indicators snapshot in Atlas
        ind_hist = self.store.history(kind="stocks", entity="AAPL", type="indicators")
        assert len(ind_hist) >= 1, "no indicators snapshot stored"
        ind_data = ind_hist[0].get("data", {})
        assert "ticker" in ind_data
        assert ind_data["ticker"] == "AAPL"
        assert "current_close" in ind_data
        # AAPL should have enough data for at least RSI
        assert "rsi_14" in ind_data

    def test_ingest_crypto_btc(self):
        """Verify crypto ticker conversion and storage."""
        result = asyncio.run(
            self.pi.ingest_ticker("BTC", "crypto", self.indicators, self.store)
        )

        assert result["status"] == "ok", f"BTC ingest failed: {result}"

        price_hist = self.store.history(kind="crypto", entity="BTC", type="price")
        assert len(price_hist) >= 1
        assert price_hist[0]["data"]["currency"] == "USD"

    def test_ingest_invalid_ticker_returns_error(self):
        """Non-existent ticker should return fetch_error, not crash."""
        result = asyncio.run(
            self.pi.ingest_ticker("ZZZZZZ999", "stocks", self.indicators, self.store)
        )
        assert result["status"] == "fetch_error"


class TestSignalChangeDetection:
    """Verify that signal changes between ingests produce events."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        _check_mongo()
        self.store = _fresh_store(tmp_path)
        self.indicators = _fresh_indicators()
        self.pi = _fresh_price_ingest()
        yield
        _cleanup_db(self.store)

    def test_first_ingest_no_signal_change(self):
        """First ingest has no previous data, so no signal_change event."""
        asyncio.run(
            self.pi.ingest_ticker("AAPL", "stocks", self.indicators, self.store)
        )

        events = self.store.recent_events(subtype="signal_change", days=1)
        aapl_events = [e for e in events
                       if e.get("data", {}).get("entity") == "AAPL"]
        assert len(aapl_events) == 0, "unexpected signal_change on first ingest"

    def test_signal_change_detected_on_second_ingest(self):
        """Seed a fake previous snapshot with different composite, then ingest."""
        # Seed a fake "previous" indicators snapshot with a different signal
        self.store.snapshot(
            kind="stocks", entity="MSFT", type="indicators",
            data={"composite": "avoid", "ticker": "MSFT"},
            source="test_seed",
        )

        # Now ingest MSFT — real data will likely produce a different composite
        result = asyncio.run(
            self.pi.ingest_ticker("MSFT", "stocks", self.indicators, self.store)
        )
        assert result["status"] == "ok"

        # If the real composite differs from "avoid", we should see an event
        if result.get("signal_change"):
            events = self.store.recent_events(subtype="signal_change", days=1)
            msft_events = [e for e in events
                           if e.get("data", {}).get("entity") == "MSFT"]
            assert len(msft_events) >= 1
            assert msft_events[0]["data"]["old_signal"] == "avoid"


class TestThresholdBreachIntegration:
    """Verify threshold checking fires against real data stored in Atlas."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        _check_mongo()
        self.store = _fresh_store(tmp_path)
        yield
        _cleanup_db(self.store)

    def test_threshold_breach_emits_event(self):
        """Create profile with always-firing threshold, store snapshot, verify event."""
        # Create a stock profile with a threshold that will always fire
        # RSI < 100 will always be true for any valid RSI reading
        self.store.put_profile(
            kind="stocks", id="THRESH_TEST",
            data={
                "name": "Threshold Test Stock",
                "signal": {
                    "thresholds": [
                        {"field": "rsi_14", "op": "<", "value": 100,
                         "severity": "high", "label": "RSI always fires"},
                    ]
                },
            },
        )

        # Store a snapshot with RSI data — this should trigger the threshold hook
        self.store.snapshot(
            kind="stocks", entity="THRESH_TEST", type="indicators",
            data={"rsi_14": 55.0, "composite": "hold"},
            source="test",
        )

        # Check for threshold_breach event
        events = self.store.recent_events(subtype="threshold_breach", days=1)
        test_events = [e for e in events
                       if e.get("data", {}).get("entity") == "THRESH_TEST"]
        assert len(test_events) >= 1, (
            f"no threshold_breach event found; all events: {events}"
        )
        breach_data = test_events[0]["data"]
        assert breach_data["kind"] == "stocks"
        assert len(breach_data["breaches"]) >= 1
        assert breach_data["breaches"][0]["label"] == "RSI always fires"
        assert breach_data["breaches"][0]["actual"] == 55.0

    def test_no_breach_when_below_threshold(self):
        """Threshold should NOT fire when condition is not met."""
        self.store.put_profile(
            kind="stocks", id="NO_BREACH_TEST",
            data={
                "name": "No Breach Test",
                "signal": {
                    "thresholds": [
                        {"field": "rsi_14", "op": "<", "value": 30,
                         "severity": "high", "label": "RSI oversold"},
                    ]
                },
            },
        )

        # RSI 55 > 30 — should NOT trigger
        self.store.snapshot(
            kind="stocks", entity="NO_BREACH_TEST", type="indicators",
            data={"rsi_14": 55.0},
            source="test",
        )

        events = self.store.recent_events(subtype="threshold_breach", days=1)
        test_events = [e for e in events
                       if e.get("data", {}).get("entity") == "NO_BREACH_TEST"]
        assert len(test_events) == 0


class TestImpactPropagationIntegration:
    """Verify event-to-profile impact mapping against real Atlas."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        _check_mongo()
        self.store = _fresh_store(tmp_path)
        yield
        _cleanup_db(self.store)

    def test_high_severity_event_creates_impact_snapshots(self):
        """Store profiles with exposure, emit high-severity event, verify impacts."""
        # Create stock profiles with country exposure
        self.store.put_profile(
            kind="stocks", id="IMPACT_TSM",
            data={
                "name": "TSMC",
                "exposure": {"countries": ["TWN", "JPN"]},
            },
        )
        self.store.put_profile(
            kind="stocks", id="IMPACT_SONY",
            data={
                "name": "Sony",
                "exposure": {"countries": ["JPN"]},
            },
        )
        self.store.put_profile(
            kind="stocks", id="IMPACT_AAPL",
            data={
                "name": "Apple",
                "exposure": {"countries": ["USA", "CHN"]},
            },
        )

        # Emit a high-severity event targeting JPN
        result = self.store.event(
            subtype="earthquake",
            summary="Major earthquake near Tokyo",
            data={"magnitude": 7.5},
            severity="high",
            countries=["JPN"],
            region="east_asia",
        )
        assert result["status"] == "ok"

        # Check that impact snapshots were created for JPN-exposed profiles
        tsm_impacts = self.store.history(
            kind="stocks", entity="IMPACT_TSM", type="impact")
        assert len(tsm_impacts) >= 1, (
            f"no impact snapshot for TSM; history: {tsm_impacts}"
        )
        assert tsm_impacts[0]["data"]["event_subtype"] == "earthquake"
        assert "JPN" in tsm_impacts[0]["data"]["matched_countries"]

        sony_impacts = self.store.history(
            kind="stocks", entity="IMPACT_SONY", type="impact")
        assert len(sony_impacts) >= 1

        # AAPL has no JPN exposure — should NOT get an impact snapshot
        aapl_impacts = self.store.history(
            kind="stocks", entity="IMPACT_AAPL", type="impact")
        assert len(aapl_impacts) == 0, (
            f"AAPL should not be impacted by JPN event: {aapl_impacts}"
        )

    def test_medium_severity_skips_propagation(self):
        """Medium-severity events should NOT trigger impact propagation."""
        self.store.put_profile(
            kind="stocks", id="IMPACT_SKIP",
            data={
                "name": "Skip Stock",
                "exposure": {"countries": ["USA"]},
            },
        )

        self.store.event(
            subtype="policy_update",
            summary="Minor policy change",
            data={"detail": "regulatory update"},
            severity="medium",
            countries=["USA"],
        )

        impacts = self.store.history(
            kind="stocks", entity="IMPACT_SKIP", type="impact")
        assert len(impacts) == 0


class TestFullPipelineIntegration:
    """End-to-end: ingest real ticker with thresholds → verify complete chain."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        _check_mongo()
        self.store = _fresh_store(tmp_path)
        self.indicators = _fresh_indicators()
        self.pi = _fresh_price_ingest()
        yield
        _cleanup_db(self.store)

    def test_ingest_with_threshold_fires_event(self):
        """Ingest AAPL with a guaranteed-to-fire threshold, verify breach event."""
        # Set up profile with always-true threshold
        self.store.put_profile(
            kind="stocks", id="AAPL",
            data={
                "name": "Apple Inc.",
                "signal": {
                    "thresholds": [
                        {"field": "current_close", "op": ">", "value": 0,
                         "severity": "medium", "label": "Price is positive"},
                    ]
                },
            },
        )

        # Ingest real data
        result = asyncio.run(
            self.pi.ingest_ticker("AAPL", "stocks", self.indicators, self.store)
        )
        assert result["status"] == "ok"

        # The indicators snapshot should have triggered the threshold hook
        events = self.store.recent_events(subtype="threshold_breach", days=1)
        aapl_events = [e for e in events
                       if e.get("data", {}).get("entity") == "AAPL"]
        assert len(aapl_events) >= 1, (
            f"threshold_breach not found after ingest; events: {events}"
        )
        assert aapl_events[0]["data"]["breaches"][0]["label"] == "Price is positive"
