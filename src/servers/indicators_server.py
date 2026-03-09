"""Technical indicators — pure-math computation layer.

No external API calls. Tools accept OHLCV price arrays and return computed
indicator values. Designed around the 3-layer hierarchy from the NexusTrade
114K-backtest study:

  Layer 1 — Fundamental Screen (debt/assets, net income — handled by profiles)
  Layer 2 — Trend Filter (200-day SMA)
  Layer 3 — Entry/Exit Timing (RSI, Bollinger Bands, MACD, EMA)

Reference:
  nexustrade.io/blog/i-analyzed-100000-backtests-to-find-the-best-trading-indicator
"""
from __future__ import annotations

import math
from fastmcp import FastMCP

mcp = FastMCP(
    "indicators",
    instructions=(
        "Technical indicator computation (no API calls). "
        "Pass OHLCV price data and get back computed indicators. "
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


if __name__ == "__main__":
    mcp.run(transport="stdio")
