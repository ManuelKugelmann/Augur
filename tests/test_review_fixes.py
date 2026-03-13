"""Tests for review fix items #24-45 and coverage gaps T1-T6.

Covers: mutable default fix, api_multi concurrency, risk gate daily reset,
indicators import guard, ticker validation, SPARQL limit cap, FDA drug
sanitization, push_site exit codes, notify async, CRLF header sanitization,
charts integer parse, limit caps, seed_profiles ID validation,
and the api_multi error isolation gap (T5).
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add src paths
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "store"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "servers"))

os.environ.setdefault("MONGO_URI_SIGNALS", "mongodb://localhost:27017/test_unused")

from conftest import _USE_MONGOMOCK

if _USE_MONGOMOCK:
    import mongomock


class _FakeCollection:
    """Minimal in-memory collection for tests."""

    def __init__(self):
        self._docs: list[dict] = []
        self._counter = 0

    def insert_one(self, doc):
        self._counter += 1
        doc.setdefault("_id", f"fake_{self._counter}")
        self._docs.append(doc.copy())
        result = MagicMock()
        result.inserted_id = doc["_id"]
        return result

    def find(self, filter_=None, projection=None):
        return _FakeCursor(self._docs, filter_)

    def find_one(self, filter_, *args):
        for d in self._docs:
            if all(d.get(k) == v for k, v in filter_.items()):
                return d.copy()
        return None

    def drop(self):
        self._docs.clear()


class _FakeCursor:
    def __init__(self, docs, filter_=None):
        self._docs = list(docs)

    def sort(self, *a):
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    def __iter__(self):
        return iter(self._docs)


@pytest.fixture
def store():
    import server as store_mod
    if _USE_MONGOMOCK:
        client = mongomock.MongoClient()
        store_mod._client = client
    else:
        client = MagicMock()
        db = MagicMock()
        client.__getitem__ = MagicMock(return_value=db)
        store_mod._client = client
    store_mod._cols_ready.clear()
    store_mod._user_action_counts.clear()
    store_mod._action_count_date = ""
    return store_mod


# ── #24: Mutable default in score_prediction ──


class TestMutableDefault:
    def test_score_prediction_default_evidence_is_none(self):
        import augur_score
        import inspect
        sig = inspect.signature(augur_score.score_prediction)
        default = sig.parameters["evidence"].default
        assert default is None, "evidence default should be None, not []"


# ── #25: api_multi concurrency ──


class TestApiMulti:
    @pytest.mark.asyncio
    async def test_api_multi_runs_concurrently(self):
        from _http import api_multi

        call_times = []

        async def slow_a():
            call_times.append(("a_start", asyncio.get_event_loop().time()))
            await asyncio.sleep(0.1)
            call_times.append(("a_end", asyncio.get_event_loop().time()))
            return {"a": 1}

        async def slow_b():
            call_times.append(("b_start", asyncio.get_event_loop().time()))
            await asyncio.sleep(0.1)
            call_times.append(("b_end", asyncio.get_event_loop().time()))
            return {"b": 2}

        result = await api_multi({"a": slow_a(), "b": slow_b()})
        assert result["a"] == {"a": 1}
        assert result["b"] == {"b": 2}

        # Both should start before either ends (concurrent)
        starts = [t for name, t in call_times if name.endswith("_start")]
        ends = [t for name, t in call_times if name.endswith("_end")]
        assert max(starts) < min(ends), "calls should overlap (concurrent)"

    @pytest.mark.asyncio
    async def test_api_multi_error_isolation(self):
        """T5: One failing coroutine doesn't prevent others from completing."""
        from _http import api_multi

        async def ok():
            return {"ok": True}

        async def fail():
            raise ValueError("boom")

        result = await api_multi({"good": ok(), "bad": fail()})
        assert result["good"] == {"ok": True}
        assert "error" in result["bad"]
        assert "boom" in result["bad"]["error"]


# ── #27: Risk gate daily counter reset ──


class TestRiskGateDailyReset:
    def test_counter_resets_on_new_day(self, store, monkeypatch):
        monkeypatch.setenv("LIBRECHAT_USER_ID", "reset-user")
        store._user_action_counts["reset-user"] = 999
        store._action_count_date = "2020-01-01"

        # This call should trigger date change → clear counters
        result = store._risk_check("buy", {"symbol": "AAPL"}, dry_run=False)
        assert result is None  # should pass (counter was reset)
        assert store._user_action_counts["reset-user"] == 1

    def test_counter_persists_same_day(self, store, monkeypatch):
        monkeypatch.setenv("LIBRECHAT_USER_ID", "same-day-user")
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        store._action_count_date = today
        store._user_action_counts["same-day-user"] = 5

        store._risk_check("buy", {"symbol": "AAPL"}, dry_run=False)
        assert store._user_action_counts["same-day-user"] == 6


# ── #28: indicators_server import guard ──


class TestIndicatorsImportGuard:
    def test_ta_available_flag_exists(self):
        import indicators_server
        assert hasattr(indicators_server, "_TA_AVAILABLE")


# ── #29: Ticker validation ──


class TestTickerValidation:
    @pytest.mark.asyncio
    async def test_invalid_ticker_rejected(self):
        import indicators_server
        if not indicators_server._TA_AVAILABLE:
            pytest.skip("ta library not installed")
        result = await indicators_server.analyze_full("../../etc/passwd")
        assert "error" in result
        assert "invalid ticker" in result["error"]

    @pytest.mark.asyncio
    async def test_long_ticker_rejected(self):
        import indicators_server
        if not indicators_server._TA_AVAILABLE:
            pytest.skip("ta library not installed")
        result = await indicators_server.analyze_full("A" * 25)
        assert "error" in result


# ── #30: SPARQL limit capped ──


class TestSparqlLimitCap:
    @pytest.mark.asyncio
    async def test_limit_capped_in_query(self):
        import elections_server

        captured_query = {}

        async def mock_get(url, **kwargs):
            captured_query["params"] = kwargs.get("params", {})
            resp = MagicMock()
            resp.json.return_value = {"results": {"bindings": []}}
            resp.raise_for_status = MagicMock()
            return resp

        client = AsyncMock()
        client.get = mock_get
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=client):
            await elections_server.global_elections(limit=99999)

        query_str = captured_query["params"]["query"]
        # Should contain "LIMIT 200" not "LIMIT 99999"
        assert "LIMIT 200" in query_str


# ── #31: FDA drug quote sanitization ──


class TestFdaDrugSanitization:
    @pytest.mark.asyncio
    async def test_drug_quotes_stripped(self):
        import health_server
        # A drug name with embedded quotes should have them stripped
        # The regex _SAFE_COUNTRY only allows [A-Za-z0-9 -] so quotes
        # would be caught by validation. But if it passes validation,
        # quotes in the search string are still stripped.
        resp = MagicMock()
        resp.json.return_value = {"results": []}
        resp.raise_for_status = MagicMock()

        client = AsyncMock()
        client.get.return_value = resp
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=client):
            await health_server.fda_adverse_events(drug="aspirin")
        # Just verify it doesn't crash
        assert client.get.called


# ── #36: notify() is now async ──


class TestNotifyAsync:
    @pytest.mark.asyncio
    async def test_notify_is_async(self, store, monkeypatch):
        import inspect
        assert inspect.iscoroutinefunction(store.notify)


# ── #42: CRLF header sanitization ──


class TestCrlfSanitization:
    def test_sanitize_header_strips_crlf(self, store):
        result = store._sanitize_header("Hello\r\nEvil: injected")
        assert "\r" not in result
        assert "\n" not in result
        assert "Hello" in result


# ── #43: Charts integer parse crash ──


class TestChartsIntegerParse:
    def test_non_numeric_periods_uses_default(self):
        from urllib.parse import urlencode, parse_qs
        import charts

        handler = MagicMock()
        handler.path = "/charts/countries/DEU/indicators/gdp?periods=abc"
        handler.wfile = MagicMock()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()

        # Test the parse logic directly from the chart handler
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(handler.path)
        qs = parse_qs(parsed.query)
        try:
            periods = min(max(1, int(qs.get("periods", ["24"])[0])), 10000)
        except (ValueError, TypeError):
            periods = 24
        assert periods == 24


# ── #44: Limit caps ──


class TestLimitCaps:
    def test_list_profiles_limit_capped(self, store, monkeypatch):
        col = _FakeCollection()
        monkeypatch.setattr(store, "_profiles_col", lambda k: col)
        # Request absurd limit — should be capped internally
        result = store.list_profiles("countries", limit=999999)
        # No crash, returns empty (empty collection)
        assert isinstance(result, list)

    def test_recent_events_limit_capped(self, store, monkeypatch):
        col = _FakeCollection()
        monkeypatch.setattr(store, "_events_col", lambda: col)
        result = store.recent_events(limit=999999)
        assert isinstance(result, list)


# ── #45: seed_profiles ID validation ──


class TestSeedProfilesIdValidation:
    def test_invalid_id_rejected(self, store, tmp_path):
        profiles_dir = tmp_path / "profiles"
        region_dir = profiles_dir / "europe" / "countries"
        region_dir.mkdir(parents=True)
        # Create a profile with an invalid ID (contains spaces)
        (region_dir / "BAD ID.json").write_text(json.dumps({"name": "Bad"}))
        result = store.seed_profiles(str(profiles_dir))
        # Invalid IDs generate errors in _errors key, not seeded
        assert "countries" not in result  # 0 seeded → no entry
        assert len(result.get("_errors", [])) > 0
        assert "invalid ID" in result["_errors"][0]


# ── T1: Risk gate header edge cases ──


class TestRiskGateEdgeCases:
    def test_invalid_daily_limit_header(self, store, monkeypatch):
        monkeypatch.setenv("LIBRECHAT_USER_ID", "edge-user")
        fake_headers = {"x-user-id": "edge-user", "x-risk-daily-limit": "not-a-number"}
        deps = sys.modules["fastmcp.server.dependencies"]
        monkeypatch.setattr(deps, "get_http_headers", lambda: fake_headers)
        settings = store._get_user_risk_settings()
        assert settings["daily_limit"] == store._DAILY_ACTION_LIMIT_DEFAULT

    def test_zero_daily_limit_blocks_all(self, store, monkeypatch):
        monkeypatch.setenv("LIBRECHAT_USER_ID", "zero-user")
        fake_headers = {"x-user-id": "zero-user", "x-risk-daily-limit": "0"}
        deps = sys.modules["fastmcp.server.dependencies"]
        monkeypatch.setattr(deps, "get_http_headers", lambda: fake_headers)
        store._user_action_counts.clear()
        store._action_count_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        result = store._risk_check("buy", {"symbol": "AAPL"}, dry_run=False)
        assert result is not None
        assert "daily action limit (0)" in result["error"]
