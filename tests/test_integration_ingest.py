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
    """Verify threshold checking against real profiles stored in Atlas.

    Directly calls threshold_checker functions (not the implicit store hook)
    to ensure clear error messages and reliable testing.
    """

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        _check_mongo()
        self.store = _fresh_store(tmp_path)
        from threshold_checker import (
            check_thresholds, get_thresholds_from_profile, max_severity,
        )
        self.check_thresholds = check_thresholds
        self.get_thresholds = get_thresholds_from_profile
        self.max_severity = max_severity
        yield
        _cleanup_db(self.store)

    def test_threshold_breach_emits_event(self):
        """Create profile with always-firing threshold, check data, store event."""
        # Create a stock profile with a threshold that will always fire
        put_result = self.store.put_profile(
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
        assert put_result.get("status") == "ok", f"put_profile failed: {put_result}"

        # Store a snapshot with RSI data
        snap_data = {"rsi_14": 55.0, "composite": "hold"}
        snap_result = self.store.snapshot(
            kind="stocks", entity="THRESH_TEST", type="indicators",
            data=snap_data, source="test",
        )
        assert snap_result.get("status") == "ok", f"snapshot failed: {snap_result}"

        # Fetch profile from Atlas and run threshold checker directly
        profile = self.store.get_profile(kind="stocks", id="THRESH_TEST")
        assert "error" not in profile, f"get_profile failed: {profile}"

        thresholds = self.get_thresholds(profile)
        assert len(thresholds) >= 1, f"no thresholds extracted: {profile}"

        breaches = self.check_thresholds(snap_data, thresholds)
        assert len(breaches) >= 1, f"no breaches detected: data={snap_data}, thresholds={thresholds}"
        assert breaches[0]["label"] == "RSI always fires"
        assert breaches[0]["actual"] == 55.0

        # Store breach event (mimics what the hook does)
        severity = self.max_severity(breaches)
        labels = [b["label"] for b in breaches]
        event_result = self.store.event(
            subtype="threshold_breach",
            summary=f"THRESH_TEST: {', '.join(labels)}",
            data={"entity": "THRESH_TEST", "kind": "stocks", "breaches": breaches},
            severity=severity,
            entities=["THRESH_TEST"],
            source="threshold_checker",
        )
        assert event_result.get("status") == "ok", f"event failed: {event_result}"

        # Verify event is retrievable
        events = self.store.recent_events(subtype="threshold_breach", days=1)
        test_events = [e for e in events
                       if e.get("data", {}).get("entity") == "THRESH_TEST"]
        assert len(test_events) >= 1, (
            f"threshold_breach event not found after explicit store; events: {events}"
        )
        breach_data = test_events[0]["data"]
        assert breach_data["kind"] == "stocks"
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

        snap_data = {"rsi_14": 55.0}
        self.store.snapshot(
            kind="stocks", entity="NO_BREACH_TEST", type="indicators",
            data=snap_data, source="test",
        )

        profile = self.store.get_profile(kind="stocks", id="NO_BREACH_TEST")
        thresholds = self.get_thresholds(profile)
        breaches = self.check_thresholds(snap_data, thresholds)
        assert len(breaches) == 0, f"unexpected breaches: {breaches}"


class TestImpactPropagationIntegration:
    """Verify event-to-profile impact mapping against real Atlas.

    Directly calls impact_mapper functions (not the implicit store hook)
    to ensure clear error messages and reliable testing.
    """

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        _check_mongo()
        self.store = _fresh_store(tmp_path)
        from impact_mapper import (
            find_exposed_profiles, propagate_event_impact, should_propagate,
        )
        self.find_exposed = find_exposed_profiles
        self.propagate = propagate_event_impact
        self.should_propagate = should_propagate
        yield
        _cleanup_db(self.store)

    def test_high_severity_event_creates_impact_snapshots(self):
        """Store profiles with exposure, emit high-severity event, verify impacts."""
        # Create stock profiles with country exposure
        for pid, name, countries in [
            ("IMPACT_TSM", "TSMC", ["TWN", "JPN"]),
            ("IMPACT_SONY", "Sony", ["JPN"]),
            ("IMPACT_AAPL", "Apple", ["USA", "CHN"]),
        ]:
            result = self.store.put_profile(
                kind="stocks", id=pid,
                data={"name": name, "exposure": {"countries": countries}},
            )
            assert result.get("status") == "ok", f"put_profile {pid} failed: {result}"

        # Store a high-severity event targeting JPN
        event_meta = {
            "type": "event",
            "subtype": "earthquake",
            "severity": "high",
            "region": "east_asia",
            "countries": ["JPN"],
            "entities": [],
            "source": "test",
        }
        event_result = self.store.event(
            subtype="earthquake",
            summary="Major earthquake near Tokyo",
            data={"magnitude": 7.5},
            severity="high",
            countries=["JPN"],
            region="east_asia",
        )
        assert event_result.get("status") == "ok", f"event failed: {event_result}"

        # Verify should_propagate agrees this is high-severity
        assert self.should_propagate("high"), "should_propagate returned False for 'high'"

        # Find exposed profiles via impact mapper
        exposed = self.find_exposed(
            countries=["JPN"],
            search_profiles_fn=self.store.search_profiles,
        )
        exposed_ids = {e["id"] for e in exposed}
        assert "IMPACT_TSM" in exposed_ids, (
            f"IMPACT_TSM not found in exposed profiles: {exposed}"
        )
        assert "IMPACT_SONY" in exposed_ids, (
            f"IMPACT_SONY not found in exposed profiles: {exposed}"
        )
        assert "IMPACT_AAPL" not in exposed_ids, (
            f"IMPACT_AAPL should not be exposed to JPN: {exposed}"
        )

        # Propagate impact (creates impact snapshots in Atlas)
        impacts = self.propagate(
            event_meta=event_meta,
            event_summary="Major earthquake near Tokyo",
            event_data={"magnitude": 7.5},
            search_profiles_fn=self.store.search_profiles,
            snapshot_fn=self.store.snapshot,
            event_id=event_result["id"],
        )
        assert len(impacts) >= 2, f"expected >=2 impact records: {impacts}"

        # Verify impact snapshots stored in Atlas
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
        assert not self.should_propagate("medium"), (
            "should_propagate should return False for 'medium'"
        )

        self.store.put_profile(
            kind="stocks", id="IMPACT_SKIP",
            data={
                "name": "Skip Stock",
                "exposure": {"countries": ["USA"]},
            },
        )

        event_meta = {
            "type": "event", "subtype": "policy_update",
            "severity": "medium", "countries": ["USA"],
        }
        impacts = self.propagate(
            event_meta=event_meta,
            event_summary="Minor policy change",
            event_data={"detail": "regulatory update"},
            search_profiles_fn=self.store.search_profiles,
            snapshot_fn=self.store.snapshot,
        )
        assert len(impacts) == 0, f"unexpected impacts for medium event: {impacts}"


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
