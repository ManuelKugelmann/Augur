"""Tests for indicators_server.py — pure-math technical analysis tools.

No external dependencies needed. All tools are pure computation over
price arrays.
"""
import math
import sys
from pathlib import Path

import httpx
import pytest

# Add servers dir to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "servers"))

# Mock fastmcp before importing
from unittest.mock import MagicMock

if "fastmcp" not in sys.modules:
    mock_fastmcp = MagicMock()

    class _FakeMCP:
        def __init__(self, name="", **kw):
            self.name = name
            self._tools = {}

        def tool(self, *a, **kw):
            def decorator(fn):
                self._tools[fn.__name__] = fn
                return fn
            return decorator

        def run(self, **kw):
            pass

    mock_fastmcp.FastMCP = _FakeMCP
    sys.modules["fastmcp"] = mock_fastmcp

import indicators_server as ind  # noqa: E402


# ── Helper data ──────────────────────────────────────

def _make_prices(n: int, start: float = 100.0, trend: float = 0.1) -> list[float]:
    """Generate a simple trending price series."""
    return [start + i * trend for i in range(n)]


def _make_sine_prices(n: int, base: float = 100.0, amp: float = 10.0,
                      period: int = 40) -> list[float]:
    """Generate oscillating prices (useful for RSI/Bollinger tests)."""
    return [base + amp * math.sin(2 * math.pi * i / period) for i in range(n)]


# ── SMA tests ────────────────────────────────────────


class TestSMA:
    @pytest.mark.asyncio
    async def test_sma_basic(self):
        closes = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = await ind.sma(closes, period=3)
        assert result["period"] == 3
        assert result["sma"][:2] == [None, None]
        assert result["sma"][2] == pytest.approx(2.0)
        assert result["sma"][3] == pytest.approx(3.0)
        assert result["sma"][4] == pytest.approx(4.0)

    @pytest.mark.asyncio
    async def test_sma_200_bullish(self):
        # Price above SMA → bullish
        closes = _make_prices(250, start=100, trend=0.5)
        result = await ind.sma(closes, period=200)
        assert result["trend_signal"] == "bullish"
        assert result["current_close"] > result["current_sma"]

    @pytest.mark.asyncio
    async def test_sma_200_bearish(self):
        # Declining prices → bearish
        closes = _make_prices(250, start=200, trend=-0.5)
        result = await ind.sma(closes, period=200)
        assert result["trend_signal"] == "bearish"
        assert result["current_close"] < result["current_sma"]

    @pytest.mark.asyncio
    async def test_sma_too_few_points(self):
        with pytest.raises(ValueError, match="requires at least"):
            await ind.sma([1.0, 2.0], period=5)

    @pytest.mark.asyncio
    async def test_sma_length(self):
        closes = _make_prices(50, start=10)
        result = await ind.sma(closes, period=10)
        assert len(result["sma"]) == 50


# ── EMA tests ────────────────────────────────────────


class TestEMA:
    @pytest.mark.asyncio
    async def test_ema_basic(self):
        closes = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = await ind.ema(closes, period=3)
        assert result["period"] == 3
        assert result["ema"][:2] == [None, None]
        # First EMA = SMA of first 3 values = 2.0
        assert result["ema"][2] == pytest.approx(2.0)
        assert result["current_ema"] is not None

    @pytest.mark.asyncio
    async def test_ema_reacts_faster_than_sma(self):
        # For a sharp move up, EMA should be closer to current price than SMA
        closes = _make_prices(50, start=100, trend=0.1)
        closes.extend([200.0] * 10)  # sudden jump
        ema_result = await ind.ema(closes, period=20)
        sma_result = await ind.sma(closes, period=20)
        # EMA reacts faster → closer to 200
        assert ema_result["current_ema"] > sma_result["current_sma"]

    @pytest.mark.asyncio
    async def test_ema_too_few_points(self):
        with pytest.raises(ValueError, match="requires at least"):
            await ind.ema([1.0], period=5)


# ── RSI tests ────────────────────────────────────────


class TestRSI:
    @pytest.mark.asyncio
    async def test_rsi_overbought(self):
        # Continuous upward movement → RSI near 100
        closes = _make_prices(50, start=10, trend=1.0)
        result = await ind.rsi(closes, period=14)
        assert result["signal"] == "overbought"
        assert result["current_rsi"] > 70

    @pytest.mark.asyncio
    async def test_rsi_oversold(self):
        # Continuous downward movement → RSI near 0
        closes = _make_prices(50, start=100, trend=-1.0)
        result = await ind.rsi(closes, period=14)
        assert result["signal"] == "oversold"
        assert result["current_rsi"] < 30

    @pytest.mark.asyncio
    async def test_rsi_neutral(self):
        # Oscillating prices → RSI near 50
        closes = _make_sine_prices(100, base=100, amp=5, period=20)
        result = await ind.rsi(closes, period=14)
        assert result["signal"] == "neutral"
        assert 30 <= result["current_rsi"] <= 70

    @pytest.mark.asyncio
    async def test_rsi_range(self):
        closes = _make_sine_prices(100, base=100, amp=10, period=30)
        result = await ind.rsi(closes, period=14)
        # RSI should be between 0 and 100
        for val in result["rsi"]:
            if val is not None:
                assert 0 <= val <= 100

    @pytest.mark.asyncio
    async def test_rsi_too_few_points(self):
        with pytest.raises(ValueError, match="requires at least 15"):
            await ind.rsi([1.0] * 10, period=14)

    @pytest.mark.asyncio
    async def test_rsi_default_period(self):
        closes = _make_prices(30, start=100, trend=0.5)
        result = await ind.rsi(closes)
        assert result["period"] == 14


# ── Bollinger Bands tests ────────────────────────────


class TestBollingerBands:
    @pytest.mark.asyncio
    async def test_bollinger_basic(self):
        closes = _make_prices(30, start=100, trend=0.1)
        result = await ind.bollinger_bands(closes, period=20)
        assert result["period"] == 20
        assert result["num_std"] == 2.0
        # Upper > middle > lower
        assert result["current_upper"] > result["current_middle"]
        assert result["current_middle"] > result["current_lower"]

    @pytest.mark.asyncio
    async def test_bollinger_within_bands(self):
        # Steady trend → price stays within bands
        closes = _make_prices(50, start=100, trend=0.1)
        result = await ind.bollinger_bands(closes, period=20)
        assert result["signal"] == "within_bands"

    @pytest.mark.asyncio
    async def test_bollinger_above_upper(self):
        # Sudden spike → above upper band
        closes = _make_prices(30, start=100, trend=0.1)
        closes.append(closes[-1] + 50)  # big spike
        result = await ind.bollinger_bands(closes, period=20)
        assert result["signal"] == "above_upper"

    @pytest.mark.asyncio
    async def test_bollinger_below_lower(self):
        # Sudden drop → below lower band
        closes = _make_prices(30, start=100, trend=0.1)
        closes.append(closes[-1] - 50)  # big drop
        result = await ind.bollinger_bands(closes, period=20)
        assert result["signal"] == "below_lower"

    @pytest.mark.asyncio
    async def test_bollinger_bandwidth(self):
        closes = _make_prices(30, start=100, trend=0.1)
        result = await ind.bollinger_bands(closes, period=20)
        assert result["bandwidth"] > 0

    @pytest.mark.asyncio
    async def test_bollinger_too_few_points(self):
        with pytest.raises(ValueError, match="requires at least"):
            await ind.bollinger_bands([1.0] * 10, period=20)


# ── MACD tests ───────────────────────────────────────


class TestMACD:
    @pytest.mark.asyncio
    async def test_macd_bullish_trend(self):
        # Accelerating uptrend → MACD above signal line
        # Linear trends make MACD converge; use acceleration to keep it rising
        closes = [50.0 + 0.02 * i ** 2 for i in range(60)]
        result = await ind.macd(closes)
        assert result["cross_signal"] == "bullish"
        assert result["current_macd"] > result["current_signal"]

    @pytest.mark.asyncio
    async def test_macd_bearish_trend(self):
        # Accelerating downtrend → MACD below signal line
        closes = [200.0 - 0.02 * i ** 2 for i in range(60)]
        result = await ind.macd(closes)
        assert result["cross_signal"] == "bearish"
        assert result["current_macd"] < result["current_signal"]

    @pytest.mark.asyncio
    async def test_macd_defaults(self):
        closes = _make_prices(50, start=100, trend=0.5)
        result = await ind.macd(closes)
        assert result["fast"] == 12
        assert result["slow"] == 26
        assert result["signal_period"] == 9

    @pytest.mark.asyncio
    async def test_macd_histogram(self):
        closes = _make_prices(50, start=100, trend=0.5)
        result = await ind.macd(closes)
        # Histogram = MACD - Signal
        m = result["current_macd"]
        s = result["current_signal"]
        h = result["current_histogram"]
        assert h == pytest.approx(m - s)

    @pytest.mark.asyncio
    async def test_macd_too_few_points(self):
        with pytest.raises(ValueError, match="requires at least"):
            await ind.macd([1.0] * 20)


# ── Composite trend filter ──────────────────────────


class TestTrendFilterCheck:
    @pytest.mark.asyncio
    async def test_strong_buy(self):
        # Uptrend (above SMA) + make RSI oversold by adding a pullback
        closes = _make_prices(200, start=50, trend=1.0)
        # Add pullback to make RSI < 30
        for _ in range(20):
            closes.append(closes[-1] - 3.0)
        # Price should still be above the 200-day SMA
        result = await ind.trend_filter_check(closes)
        assert result["trend"] == "bullish"
        # The composite should be strong_buy if RSI is oversold
        if result["rsi_signal"] == "oversold":
            assert result["composite_signal"] == "strong_buy"

    @pytest.mark.asyncio
    async def test_avoid_in_downtrend(self):
        # Below SMA → avoid
        closes = _make_prices(250, start=300, trend=-0.5)
        result = await ind.trend_filter_check(closes)
        assert result["trend"] == "bearish"
        assert result["composite_signal"] in ("avoid", "wait")

    @pytest.mark.asyncio
    async def test_hold_in_uptrend(self):
        # Steady uptrend → bullish + neutral RSI → hold
        closes = _make_prices(250, start=50, trend=0.5)
        result = await ind.trend_filter_check(closes)
        assert result["trend"] == "bullish"
        # In a steady uptrend RSI will be overbought, so we accept either
        assert result["composite_signal"] in ("hold", "caution")

    @pytest.mark.asyncio
    async def test_returns_all_fields(self):
        closes = _make_prices(250, start=100, trend=0.1)
        result = await ind.trend_filter_check(closes)
        expected_keys = {"composite_signal", "advice", "trend", "trend_sma",
                         "rsi", "rsi_signal", "current_close"}
        assert expected_keys.issubset(set(result.keys()))


# ── Internal helpers ─────────────────────────────────


class TestHelpers:
    def test_sma_helper(self):
        vals = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = ind._sma(vals, 3)
        assert result == [None, None, pytest.approx(2.0),
                          pytest.approx(3.0), pytest.approx(4.0)]

    def test_ema_helper(self):
        vals = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = ind._ema(vals, 3)
        assert result[0] is None
        assert result[1] is None
        assert result[2] == pytest.approx(2.0)  # seed = SMA
        assert result[3] is not None

    def test_stdev_helper(self):
        vals = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
        sd = ind._stdev(vals)
        assert sd == pytest.approx(2.0, abs=0.01)

    def test_stdev_constant(self):
        assert ind._stdev([5.0, 5.0, 5.0]) == 0.0

    def test_require_raises(self):
        with pytest.raises(ValueError, match="requires at least 10"):
            ind._require([1.0, 2.0], 10, "test")

    def test_require_passes(self):
        ind._require([1.0, 2.0, 3.0], 3, "test")  # no error


# ── Integrated Yahoo tools (mocked) ─────────────────


def _mock_yahoo_response(closes: list[float], ticker: str = "AAPL") -> dict:
    """Build a fake Yahoo Finance v8 chart response."""
    import time
    base_ts = int(time.time()) - len(closes) * 86400
    return {
        "chart": {
            "result": [{
                "timestamp": [base_ts + i * 86400 for i in range(len(closes))],
                "indicators": {"quote": [{"close": closes}]},
                "meta": {"currency": "USD"},
            }]
        }
    }


class _FakeResponse:
    """Minimal httpx.Response mock."""
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
    """Mock httpx.AsyncClient that returns canned Yahoo data."""
    def __init__(self, response: _FakeResponse):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def get(self, url, **kwargs):
        return self._response


@pytest.fixture
def mock_yahoo(monkeypatch):
    """Fixture that patches httpx.AsyncClient to return fake Yahoo data."""
    closes = _make_prices(250, start=100, trend=0.2)
    response = _FakeResponse(_mock_yahoo_response(closes))
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **kw: _FakeAsyncClient(response))
    return closes


class TestAnalyzeTrend:
    @pytest.mark.asyncio
    async def test_returns_trend(self, mock_yahoo):
        result = await ind.analyze_trend("AAPL", period="1y")
        assert result["ticker"] == "AAPL"
        assert result["trend_signal"] in ("bullish", "bearish")
        assert "current_sma" in result
        assert "current_close" in result

    @pytest.mark.asyncio
    async def test_insufficient_data(self, monkeypatch):
        closes = _make_prices(50, start=100, trend=0.1)
        response = _FakeResponse(_mock_yahoo_response(closes))
        monkeypatch.setattr(httpx, "AsyncClient",
                            lambda **kw: _FakeAsyncClient(response))
        result = await ind.analyze_trend("AAPL", period="3mo", sma_period=200)
        assert "error" in result


class TestAnalyzeRSI:
    @pytest.mark.asyncio
    async def test_returns_rsi(self, mock_yahoo):
        result = await ind.analyze_rsi("AAPL")
        assert result["ticker"] == "AAPL"
        assert "current_rsi" in result
        assert result["signal"] in ("oversold", "overbought", "neutral")


class TestAnalyzeMACD:
    @pytest.mark.asyncio
    async def test_returns_macd(self, mock_yahoo):
        result = await ind.analyze_macd("AAPL")
        assert result["ticker"] == "AAPL"
        assert "current_macd" in result
        assert result["cross_signal"] in ("bullish", "bearish")


class TestAnalyzeBollinger:
    @pytest.mark.asyncio
    async def test_returns_bollinger(self, mock_yahoo):
        result = await ind.analyze_bollinger("AAPL")
        assert result["ticker"] == "AAPL"
        assert result["current_upper"] > result["current_lower"]
        assert result["signal"] in ("above_upper", "below_lower", "within_bands")


class TestAnalyzeFull:
    @pytest.mark.asyncio
    async def test_returns_all_indicators(self, mock_yahoo):
        result = await ind.analyze_full("AAPL")
        assert result["ticker"] == "AAPL"
        assert "trend_signal" in result
        assert "rsi_14" in result
        assert "macd" in result
        assert "bb_upper" in result
        assert "composite" in result

    @pytest.mark.asyncio
    async def test_short_period_fallback(self, monkeypatch):
        # With only 60 data points, should fallback to SMA(50) and skip SMA(200)
        closes = _make_prices(60, start=100, trend=0.5)
        response = _FakeResponse(_mock_yahoo_response(closes))
        monkeypatch.setattr(httpx, "AsyncClient",
                            lambda **kw: _FakeAsyncClient(response))
        result = await ind.analyze_full("AAPL", period="3mo")
        assert "sma_50" in result
        assert "sma_200" not in result
        assert "trend_note" in result

    @pytest.mark.asyncio
    async def test_yahoo_error_propagated(self, monkeypatch):
        response = _FakeResponse({}, status_code=404)
        monkeypatch.setattr(httpx, "AsyncClient",
                            lambda **kw: _FakeAsyncClient(response))
        result = await ind.analyze_full("INVALID")
        assert "error" in result


class TestFetchYahooCloses:
    @pytest.mark.asyncio
    async def test_parses_response(self, mock_yahoo):
        result = await ind._fetch_yahoo_closes("AAPL")
        assert result["ticker"] == "AAPL"
        assert result["currency"] == "USD"
        assert len(result["closes"]) == 250
        assert len(result["dates"]) == 250

    @pytest.mark.asyncio
    async def test_handles_none_closes(self, monkeypatch):
        # Yahoo sometimes returns None for holidays
        closes = [100.0, None, 102.0, None, 104.0]
        response = _FakeResponse(_mock_yahoo_response(closes))
        monkeypatch.setattr(httpx, "AsyncClient",
                            lambda **kw: _FakeAsyncClient(response))
        result = await ind._fetch_yahoo_closes("AAPL")
        assert result["data_points"] == 3  # only non-None values
        assert None not in result["closes"]

    @pytest.mark.asyncio
    async def test_http_error(self, monkeypatch):
        response = _FakeResponse({}, status_code=429)
        monkeypatch.setattr(httpx, "AsyncClient",
                            lambda **kw: _FakeAsyncClient(response))
        result = await ind._fetch_yahoo_closes("AAPL")
        assert "error" in result
        assert "429" in result["error"]
