"""Technical indicators — computation + integrated Yahoo Finance tools.

Two tiers of tools:
  1. Pure-math tools: accept OHLCV arrays, return computed indicators
  2. Integrated tools: fetch prices from Yahoo Finance, compute indicators,
     return everything in one call (analyze_* prefix)

Designed around the 3-layer hierarchy from the NexusTrade 114K-backtest study:

  Layer 1 — Fundamental Screen (debt/assets, net income — handled by profiles)
  Layer 2 — Trend Filter (200-day SMA)
  Layer 3 — Entry/Exit Timing (RSI, Bollinger Bands, MACD, EMA)

Reference:
  nexustrade.io/blog/i-analyzed-100000-backtests-to-find-the-best-trading-indicator
"""
from __future__ import annotations

import math
import httpx
from fastmcp import FastMCP

mcp = FastMCP(
    "indicators",
    instructions=(
        "Technical indicator computation. Two modes: "
        "(1) Pass raw price arrays to sma/ema/rsi/bollinger_bands/macd tools. "
        "(2) Use analyze_* tools to fetch Yahoo Finance prices + compute "
        "indicators in one call — no need to chain tools. "
        "Best practice from 114K backtests: use 200-day SMA as trend filter "
        "(Layer 2), then RSI/Bollinger/MACD for entry/exit timing (Layer 3)."
    ),
)


# ── Helpers ───────────────────────────────────────────


def _require(values: list[float], min_len: int, name: str) -> None:
    """Raise ValueError if not enough data points."""
    if len(values) < min_len:
        raise ValueError(
            f"{name} requires at least {min_len} data points, got {len(values)}"
        )


def _sma(values: list[float], period: int) -> list[float | None]:
    """Simple Moving Average."""
    result: list[float | None] = [None] * (period - 1)
    window_sum = sum(values[:period])
    result.append(window_sum / period)
    for i in range(period, len(values)):
        window_sum += values[i] - values[i - period]
        result.append(window_sum / period)
    return result


def _ema(values: list[float], period: int) -> list[float | None]:
    """Exponential Moving Average."""
    k = 2.0 / (period + 1)
    result: list[float | None] = [None] * (period - 1)
    # Seed with SMA of first `period` values
    ema_val = sum(values[:period]) / period
    result.append(ema_val)
    for i in range(period, len(values)):
        ema_val = values[i] * k + ema_val * (1 - k)
        result.append(ema_val)
    return result


def _stdev(values: list[float]) -> float:
    """Population standard deviation."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    return math.sqrt(sum((v - mean) ** 2 for v in values) / n)


# ── Layer 2: Trend Filter ────────────────────────────


@mcp.tool()
async def sma(
    closes: list[float],
    period: int = 200,
) -> dict:
    """Simple Moving Average — the #1 indicator from 114K backtests.

    Best use: 200-day SMA as trend filter. Only take buy signals when
    price > SMA(200). Prevents whipsaws in bear markets.

    closes: list of closing prices (oldest first).
    period: lookback window (default 200).

    Returns the SMA series and a trend_signal ("bullish" if last close > SMA,
    "bearish" otherwise).
    """
    _require(closes, period, f"SMA({period})")
    sma_vals = _sma(closes, period)
    last_sma = sma_vals[-1]
    last_close = closes[-1]
    return {
        "period": period,
        "sma": sma_vals,
        "current_sma": last_sma,
        "current_close": last_close,
        "trend_signal": "bullish" if last_close > last_sma else "bearish",
        "description": (
            f"SMA({period}): {last_sma:.4f}. "
            f"Price {'above' if last_close > last_sma else 'below'} trend filter."
        ),
    }


@mcp.tool()
async def ema(
    closes: list[float],
    period: int = 50,
) -> dict:
    """Exponential Moving Average.

    Reacts faster than SMA. Common periods: 12, 26, 50.
    Avoid very short periods (1-3 day) — study shows they produce noise.

    closes: list of closing prices (oldest first).
    period: lookback window (default 50).
    """
    _require(closes, period, f"EMA({period})")
    ema_vals = _ema(closes, period)
    return {
        "period": period,
        "ema": ema_vals,
        "current_ema": ema_vals[-1],
        "current_close": closes[-1],
    }


# ── Layer 3: Entry/Exit Timing ──────────────────────


@mcp.tool()
async def rsi(
    closes: list[float],
    period: int = 14,
) -> dict:
    """Relative Strength Index — mean-reversion entry/exit signal.

    Best use: Layer 3 entry timing. Buy when RSI < 30 (oversold),
    sell when RSI > 70 (overbought). ONLY use after confirming
    Layer 2 trend filter (200-day SMA) is bullish.

    closes: list of closing prices (oldest first).
    period: lookback (default 14 — the standard).
    """
    _require(closes, period + 1, f"RSI({period})")
    # Calculate price changes
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]

    # Initial average gain/loss over first `period` deltas
    gains = [max(d, 0) for d in deltas[:period]]
    losses = [max(-d, 0) for d in deltas[:period]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    rsi_vals: list[float | None] = [None] * period
    if avg_loss == 0:
        rsi_vals.append(100.0)
    else:
        rs = avg_gain / avg_loss
        rsi_vals.append(100 - 100 / (1 + rs))

    # Smoothed RSI for remaining periods
    for i in range(period, len(deltas)):
        gain = max(deltas[i], 0)
        loss = max(-deltas[i], 0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        if avg_loss == 0:
            rsi_vals.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_vals.append(100 - 100 / (1 + rs))

    current_rsi = rsi_vals[-1]
    if current_rsi is not None:
        if current_rsi < 30:
            signal = "oversold"
        elif current_rsi > 70:
            signal = "overbought"
        else:
            signal = "neutral"
    else:
        signal = "insufficient_data"

    return {
        "period": period,
        "rsi": rsi_vals,
        "current_rsi": current_rsi,
        "signal": signal,
        "description": f"RSI({period}): {current_rsi:.2f} — {signal}.",
    }


@mcp.tool()
async def bollinger_bands(
    closes: list[float],
    period: int = 20,
    num_std: float = 2.0,
) -> dict:
    """Bollinger Bands — volatility-based entry/exit signal.

    Best use: Layer 3. Upper band breakout for momentum entry,
    lower band touch for mean-reversion entry. Use 20-day period.

    closes: list of closing prices (oldest first).
    period: SMA period (default 20).
    num_std: standard deviation multiplier (default 2.0).
    """
    _require(closes, period, f"Bollinger({period})")
    middle = _sma(closes, period)
    upper: list[float | None] = []
    lower: list[float | None] = []

    for i in range(len(closes)):
        if middle[i] is None:
            upper.append(None)
            lower.append(None)
        else:
            window = closes[i - period + 1 : i + 1]
            sd = _stdev(window)
            upper.append(middle[i] + num_std * sd)
            lower.append(middle[i] - num_std * sd)

    last_close = closes[-1]
    last_upper = upper[-1]
    last_lower = lower[-1]
    last_middle = middle[-1]

    if last_close > last_upper:
        signal = "above_upper"
    elif last_close < last_lower:
        signal = "below_lower"
    else:
        signal = "within_bands"

    bandwidth = (last_upper - last_lower) / last_middle if last_middle else 0

    return {
        "period": period,
        "num_std": num_std,
        "upper": upper,
        "middle": middle,
        "lower": lower,
        "current_close": last_close,
        "current_upper": last_upper,
        "current_middle": last_middle,
        "current_lower": last_lower,
        "bandwidth": round(bandwidth, 6),
        "signal": signal,
        "description": (
            f"BB({period},{num_std}): price {signal.replace('_', ' ')}. "
            f"Bandwidth: {bandwidth:.4f}."
        ),
    }


@mcp.tool()
async def macd(
    closes: list[float],
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> dict:
    """MACD — Moving Average Convergence Divergence.

    Layer 3 momentum/trend signal. Bullish when MACD crosses above signal
    line, bearish when it crosses below.

    closes: list of closing prices (oldest first).
    fast: fast EMA period (default 12).
    slow: slow EMA period (default 26).
    signal_period: signal line EMA period (default 9).
    """
    _require(closes, slow + signal_period, f"MACD({fast},{slow},{signal_period})")
    fast_ema = _ema(closes, fast)
    slow_ema = _ema(closes, slow)

    # MACD line = fast EMA - slow EMA
    macd_line: list[float | None] = []
    for f_val, s_val in zip(fast_ema, slow_ema):
        if f_val is None or s_val is None:
            macd_line.append(None)
        else:
            macd_line.append(f_val - s_val)

    # Signal line = EMA of MACD line (only non-None values)
    macd_valid = [v for v in macd_line if v is not None]
    signal_ema = _ema(macd_valid, signal_period)

    # Align signal line with macd_line
    signal_line: list[float | None] = [None] * (len(macd_line) - len(signal_ema))
    signal_line.extend(signal_ema)

    # Histogram = MACD - Signal
    histogram: list[float | None] = []
    for m_val, s_val in zip(macd_line, signal_line):
        if m_val is None or s_val is None:
            histogram.append(None)
        else:
            histogram.append(m_val - s_val)

    current_macd = macd_line[-1]
    current_signal = signal_line[-1]
    current_hist = histogram[-1]

    if current_macd is not None and current_signal is not None:
        cross_signal = "bullish" if current_macd > current_signal else "bearish"
    else:
        cross_signal = "insufficient_data"

    return {
        "fast": fast,
        "slow": slow,
        "signal_period": signal_period,
        "macd_line": macd_line,
        "signal_line": signal_line,
        "histogram": histogram,
        "current_macd": current_macd,
        "current_signal": current_signal,
        "current_histogram": current_hist,
        "cross_signal": cross_signal,
        "description": (
            f"MACD({fast},{slow},{signal_period}): {cross_signal}. "
            f"MACD={current_macd:.4f}, Signal={current_signal:.4f}."
        ),
    }


# ── Multi-indicator composite ───────────────────────


@mcp.tool()
async def trend_filter_check(
    closes: list[float],
    sma_period: int = 200,
    rsi_period: int = 14,
) -> dict:
    """3-layer trend check — combines SMA trend filter + RSI timing.

    Implements the winning pattern from 114K backtests:
    1. Check if price is above SMA(200) → market is safe
    2. Check RSI(14) for entry timing → oversold = buy opportunity

    Returns a combined assessment with actionable signal.

    closes: list of closing prices (oldest first). Need at least 200 points.
    """
    _require(closes, sma_period, "trend_filter_check")

    sma_result = await sma(closes, sma_period)
    rsi_result = await rsi(closes, rsi_period)

    trend_ok = sma_result["trend_signal"] == "bullish"
    rsi_signal = rsi_result["signal"]

    if trend_ok and rsi_signal == "oversold":
        composite = "strong_buy"
        advice = "Trend bullish + RSI oversold — high-probability buy zone."
    elif trend_ok and rsi_signal == "neutral":
        composite = "hold"
        advice = "Trend bullish, RSI neutral — hold or wait for pullback."
    elif trend_ok and rsi_signal == "overbought":
        composite = "caution"
        advice = "Trend bullish but RSI overbought — consider taking profits."
    elif not trend_ok and rsi_signal == "oversold":
        composite = "wait"
        advice = "RSI oversold but below SMA — potential bear trap, wait for trend confirmation."
    else:
        composite = "avoid"
        advice = "Below trend filter — stay out per 200-day SMA rule."

    return {
        "composite_signal": composite,
        "advice": advice,
        "trend": sma_result["trend_signal"],
        "trend_sma": sma_result["current_sma"],
        "rsi": rsi_result["current_rsi"],
        "rsi_signal": rsi_signal,
        "current_close": closes[-1],
    }


# ── Yahoo Finance price fetching ─────────────────────


async def _fetch_yahoo_closes(
    ticker: str, period: str = "1y", interval: str = "1d"
) -> dict:
    """Fetch historical closing prices from Yahoo Finance v8 chart API.

    Returns {"closes": [...], "dates": [...], "ticker": str, "currency": str}
    or {"error": str} on failure.
    """
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"range": period, "interval": interval, "includePrePost": "false"}
    headers = {"User-Agent": "TradingAssistant/1.0"}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(url, params=params, headers=headers)
            r.raise_for_status()
            data = r.json()
        result = data["chart"]["result"][0]
        timestamps = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
        currency = result.get("meta", {}).get("currency", "USD")
        # Filter out None values (market holidays)
        paired = [(t, c) for t, c in zip(timestamps, closes) if c is not None]
        if not paired:
            return {"error": f"No price data returned for {ticker}"}
        from datetime import datetime, timezone
        dates = [
            datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
            for t, _ in paired
        ]
        clean_closes = [float(c) for _, c in paired]
        return {
            "closes": clean_closes,
            "dates": dates,
            "ticker": ticker.upper(),
            "currency": currency,
            "data_points": len(clean_closes),
        }
    except httpx.HTTPStatusError as e:
        return {"error": f"Yahoo Finance HTTP {e.response.status_code} for {ticker}"}
    except (KeyError, IndexError, TypeError) as e:
        return {"error": f"Yahoo Finance parse error for {ticker}: {e}"}
    except httpx.RequestError as e:
        return {"error": f"Yahoo Finance request failed for {ticker}: {e}"}


# ── Integrated tools (fetch + compute) ──────────────


@mcp.tool()
async def analyze_trend(
    ticker: str,
    period: str = "1y",
    sma_period: int = 200,
) -> dict:
    """Fetch prices for a ticker and compute SMA trend filter.

    One-call alternative to: yahoo-finance → get closes → ta_sma.
    Uses Yahoo Finance (free, no API key needed).

    ticker: stock/ETF/index symbol (e.g. AAPL, SPY, ^GSPC).
    period: price history range (1mo, 3mo, 6mo, 1y, 2y, 5y).
    sma_period: SMA lookback (default 200 — the #1 indicator).
    """
    prices = await _fetch_yahoo_closes(ticker, period)
    if "error" in prices:
        return prices
    closes = prices["closes"]
    if len(closes) < sma_period:
        return {
            "error": f"Only {len(closes)} data points for {ticker}, "
            f"need {sma_period} for SMA({sma_period}). Try a longer period."
        }
    sma_result = await sma(closes, sma_period)
    return {
        "ticker": prices["ticker"],
        "currency": prices["currency"],
        "data_points": prices["data_points"],
        "date_range": f"{prices['dates'][0]} to {prices['dates'][-1]}",
        "current_close": closes[-1],
        "current_sma": sma_result["current_sma"],
        "trend_signal": sma_result["trend_signal"],
        "description": sma_result["description"],
    }


@mcp.tool()
async def analyze_rsi(
    ticker: str,
    period: str = "3mo",
    rsi_period: int = 14,
) -> dict:
    """Fetch prices for a ticker and compute RSI.

    ticker: stock/ETF/index symbol (e.g. AAPL, SPY).
    period: price history range (1mo, 3mo, 6mo, 1y).
    rsi_period: RSI lookback (default 14).
    """
    prices = await _fetch_yahoo_closes(ticker, period)
    if "error" in prices:
        return prices
    closes = prices["closes"]
    if len(closes) < rsi_period + 1:
        return {"error": f"Not enough data for RSI({rsi_period})"}
    rsi_result = await rsi(closes, rsi_period)
    return {
        "ticker": prices["ticker"],
        "currency": prices["currency"],
        "date_range": f"{prices['dates'][0]} to {prices['dates'][-1]}",
        "current_close": closes[-1],
        "current_rsi": rsi_result["current_rsi"],
        "signal": rsi_result["signal"],
        "description": rsi_result["description"],
    }


@mcp.tool()
async def analyze_macd(
    ticker: str,
    period: str = "6mo",
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> dict:
    """Fetch prices for a ticker and compute MACD.

    ticker: stock/ETF/index symbol (e.g. AAPL, MSFT).
    period: price history range (3mo, 6mo, 1y).
    """
    prices = await _fetch_yahoo_closes(ticker, period)
    if "error" in prices:
        return prices
    closes = prices["closes"]
    min_needed = slow + signal_period
    if len(closes) < min_needed:
        return {"error": f"Not enough data for MACD({fast},{slow},{signal_period})"}
    macd_result = await macd(closes, fast, slow, signal_period)
    return {
        "ticker": prices["ticker"],
        "currency": prices["currency"],
        "date_range": f"{prices['dates'][0]} to {prices['dates'][-1]}",
        "current_close": closes[-1],
        "current_macd": macd_result["current_macd"],
        "current_signal": macd_result["current_signal"],
        "current_histogram": macd_result["current_histogram"],
        "cross_signal": macd_result["cross_signal"],
        "description": macd_result["description"],
    }


@mcp.tool()
async def analyze_bollinger(
    ticker: str,
    period: str = "3mo",
    bb_period: int = 20,
    num_std: float = 2.0,
) -> dict:
    """Fetch prices for a ticker and compute Bollinger Bands.

    ticker: stock/ETF/index symbol (e.g. AAPL, SPY).
    period: price history range (1mo, 3mo, 6mo, 1y).
    """
    prices = await _fetch_yahoo_closes(ticker, period)
    if "error" in prices:
        return prices
    closes = prices["closes"]
    if len(closes) < bb_period:
        return {"error": f"Not enough data for Bollinger({bb_period})"}
    bb_result = await bollinger_bands(closes, bb_period, num_std)
    return {
        "ticker": prices["ticker"],
        "currency": prices["currency"],
        "date_range": f"{prices['dates'][0]} to {prices['dates'][-1]}",
        "current_close": closes[-1],
        "current_upper": bb_result["current_upper"],
        "current_middle": bb_result["current_middle"],
        "current_lower": bb_result["current_lower"],
        "bandwidth": bb_result["bandwidth"],
        "signal": bb_result["signal"],
        "description": bb_result["description"],
    }


@mcp.tool()
async def analyze_full(
    ticker: str,
    period: str = "1y",
) -> dict:
    """Full technical analysis for a ticker — all indicators in one call.

    Fetches 1 year of prices from Yahoo Finance, then computes:
    - SMA(200) trend filter (Layer 2)
    - RSI(14) entry/exit timing (Layer 3)
    - MACD(12,26,9) momentum (Layer 3)
    - Bollinger Bands(20,2) volatility (Layer 3)
    - Composite trend filter signal

    This is the recommended single-call tool for complete analysis.

    ticker: stock/ETF/index/crypto symbol (AAPL, SPY, ^GSPC, BTC-USD).
    period: price history range (default 1y; use 2y for more SMA context).
    """
    prices = await _fetch_yahoo_closes(ticker, period)
    if "error" in prices:
        return prices
    closes = prices["closes"]

    result: dict = {
        "ticker": prices["ticker"],
        "currency": prices["currency"],
        "data_points": prices["data_points"],
        "date_range": f"{prices['dates'][0]} to {prices['dates'][-1]}",
        "current_close": closes[-1],
    }

    # SMA(200) — may not have enough data for short periods
    if len(closes) >= 200:
        sma_result = await sma(closes, 200)
        result["sma_200"] = sma_result["current_sma"]
        result["trend_signal"] = sma_result["trend_signal"]
    elif len(closes) >= 50:
        sma_result = await sma(closes, 50)
        result["sma_50"] = sma_result["current_sma"]
        result["trend_signal"] = sma_result["trend_signal"]
        result["trend_note"] = "Using SMA(50) — not enough data for SMA(200)"
    else:
        result["trend_signal"] = "insufficient_data"

    # RSI(14)
    if len(closes) >= 15:
        rsi_result = await rsi(closes, 14)
        result["rsi_14"] = rsi_result["current_rsi"]
        result["rsi_signal"] = rsi_result["signal"]

    # MACD(12,26,9)
    if len(closes) >= 35:
        macd_result = await macd(closes, 12, 26, 9)
        result["macd"] = macd_result["current_macd"]
        result["macd_signal_line"] = macd_result["current_signal"]
        result["macd_histogram"] = macd_result["current_histogram"]
        result["macd_cross"] = macd_result["cross_signal"]

    # Bollinger Bands(20,2)
    if len(closes) >= 20:
        bb_result = await bollinger_bands(closes, 20, 2.0)
        result["bb_upper"] = bb_result["current_upper"]
        result["bb_middle"] = bb_result["current_middle"]
        result["bb_lower"] = bb_result["current_lower"]
        result["bb_bandwidth"] = bb_result["bandwidth"]
        result["bb_signal"] = bb_result["signal"]

    # Composite signal
    if result.get("trend_signal") in ("bullish", "bearish") and "rsi_signal" in result:
        trend_ok = result["trend_signal"] == "bullish"
        rsi_sig = result["rsi_signal"]
        if trend_ok and rsi_sig == "oversold":
            result["composite"] = "strong_buy"
        elif trend_ok and rsi_sig == "neutral":
            result["composite"] = "hold"
        elif trend_ok and rsi_sig == "overbought":
            result["composite"] = "caution"
        elif not trend_ok and rsi_sig == "oversold":
            result["composite"] = "wait"
        else:
            result["composite"] = "avoid"

    return result


if __name__ == "__main__":
    mcp.run(transport="stdio")
