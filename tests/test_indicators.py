"""Tests for indicators_server.py — composite analysis + Yahoo integration.

Raw indicator math is handled by the ta library (pre-tested).
We only test: Yahoo fetch, composite signal logic, error handling.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required")

# Add servers dir to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "servers"))

# Mock fastmcp before importing
if "fastmcp" not in sys.modules:
    mock_fastmcp = MagicMock()

    class _FakeMCP:
        def __init__(self, name="", **kw):
            self.name = name

        def tool(self, *a, **kw):
            def decorator(fn):
                return fn
            return decorator

        def run(self, **kw):
            pass

    mock_fastmcp.FastMCP = _FakeMCP
    sys.modules["fastmcp"] = mock_fastmcp

pytest.importorskip("ta", reason="ta library not installed (sandbox: SETUPTOOLS_USE_DISTUTILS=stdlib pip install ta --no-build-isolation)")
import indicators_server as ind  # noqa: E402


# ── Mock Yahoo responses ─────────────────────────────


def _mock_yahoo_response(n: int, start: float = 100.0, trend: float = 0.2) -> dict:
    """Build a fake Yahoo Finance v8 chart response with n data points."""
    import time
    base_ts = int(time.time()) - n * 86400
    closes = [start + i * trend for i in range(n)]
    return {
        "chart": {
            "result": [{
                "timestamp": [base_ts + i * 86400 for i in range(n)],
                "indicators": {"quote": [{
                    "open": [c - 0.5 for c in closes],
                    "high": [c + 1.0 for c in closes],
                    "low": [c - 1.0 for c in closes],
                    "close": closes,
                    "volume": [1000000] * n,
                }]},
                "meta": {"currency": "USD"},
            }]
        }
    }


class _FakeResponse:
    def __init__(self, data: dict, status_code: int = 200):
        self._data = data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error", request=MagicMock(), response=self
            )

    def json(self):
        return self._data


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def get(self, url, **kwargs):
        return self._response


@pytest.fixture
def mock_yahoo_250(monkeypatch):
    """250 data points — enough for SMA(200)."""
    response = _FakeResponse(_mock_yahoo_response(250))
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **kw: _FakeAsyncClient(response))


@pytest.fixture
def mock_yahoo_60(monkeypatch):
    """60 data points — enough for SMA(50) but not SMA(200)."""
    response = _FakeResponse(_mock_yahoo_response(60))
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **kw: _FakeAsyncClient(response))


# ── analyze_full tests ───────────────────────────────


class TestAnalyzeFull:
    @pytest.mark.asyncio
    async def test_returns_all_indicators(self, mock_yahoo_250):
        result = await ind.analyze_full("AAPL")
        assert result["ticker"] == "AAPL"
        assert result["currency"] == "USD"
        assert "trend_signal" in result
        assert "rsi_14" in result
        assert "macd" in result
        assert "bb_upper" in result
        assert "composite" in result
        assert "advice" in result

    @pytest.mark.asyncio
    async def test_sma50_fallback(self, mock_yahoo_60):
        result = await ind.analyze_full("AAPL", period="3mo")
        assert "sma_50" in result
        assert "sma_200" not in result
        assert "trend_note" in result

    @pytest.mark.asyncio
    async def test_composite_signals(self, mock_yahoo_250):
        result = await ind.analyze_full("AAPL")
        assert result["composite"] in (
            "strong_buy", "hold", "caution", "wait", "avoid"
        )

    @pytest.mark.asyncio
    async def test_yahoo_error(self, monkeypatch):
        response = _FakeResponse({}, status_code=404)
        monkeypatch.setattr(httpx, "AsyncClient",
                            lambda **kw: _FakeAsyncClient(response))
        result = await ind.analyze_full("INVALID")
        assert "error" in result


# ── Yahoo fetch tests ────────────────────────────────


class TestFetchYahoo:
    @pytest.mark.asyncio
    async def test_parses_ohlcv(self, mock_yahoo_250):
        result = await ind._fetch_yahoo_ohlcv("AAPL")
        assert result["ticker"] == "AAPL"
        assert result["currency"] == "USD"
        assert len(result["df"]) == 250
        assert list(result["df"].columns) == ["open", "high", "low", "close", "volume"]

    @pytest.mark.asyncio
    async def test_filters_none(self, monkeypatch):
        data = _mock_yahoo_response(5)
        # Inject None closes
        data["chart"]["result"][0]["indicators"]["quote"][0]["close"] = [
            100.0, None, 102.0, None, 104.0
        ]
        response = _FakeResponse(data)
        monkeypatch.setattr(httpx, "AsyncClient",
                            lambda **kw: _FakeAsyncClient(response))
        result = await ind._fetch_yahoo_ohlcv("AAPL")
        assert len(result["df"]) == 3

    @pytest.mark.asyncio
    async def test_http_error(self, monkeypatch):
        response = _FakeResponse({}, status_code=429)
        monkeypatch.setattr(httpx, "AsyncClient",
                            lambda **kw: _FakeAsyncClient(response))
        result = await ind._fetch_yahoo_ohlcv("AAPL")
        assert "error" in result
        assert "429" in result["error"]
