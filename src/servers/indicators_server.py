"""Technical indicators — composite analysis tools with Yahoo Finance integration.

Raw indicator computation (SMA, RSI, MACD, Bollinger) is handled by the
finance MCP (finance-mcp-server package, using ta library).

This server adds the unique composite analysis layer based on the NexusTrade
114K-backtest study — the 3-layer hierarchy:

  Layer 1 — Fundamental Screen (debt/assets, net income — via finance MCP)
  Layer 2 — Trend Filter (200-day SMA)
  Layer 3 — Entry/Exit Timing (RSI, Bollinger Bands, MACD, EMA)

Tools here fetch prices from Yahoo Finance and compute a composite signal
combining multiple indicators into an actionable assessment.

Reference:
  nexustrade.io/blog/i-analyzed-100000-backtests-to-find-the-best-trading-indicator
"""
from datetime import datetime, timezone

import httpx
import pandas as pd
from ta.trend import SMAIndicator, EMAIndicator, MACD as TAmacd
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands
from fastmcp import FastMCP

mcp = FastMCP(
    "indicators",
    instructions=(
        "Composite technical analysis tools. Use analyze_full for a complete "
        "multi-indicator assessment of any ticker in one call. "
        "For raw individual indicators, use the finance MCP's "
        "get_technical_analysis tool instead. "
        "Best practice from 114K backtests: SMA(200) trend filter + "
        "RSI/MACD/Bollinger for entry/exit timing."
    ),
)


# ── Yahoo Finance price fetching ─────────────────────


async def _fetch_yahoo_ohlcv(
    ticker: str, period: str = "1y", interval: str = "1d"
) -> dict:
    """Fetch historical OHLCV data from Yahoo Finance v8 chart API.

    Returns {"df": pd.DataFrame, "ticker": str, "currency": str}
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
        quote = result["indicators"]["quote"][0]
        currency = result.get("meta", {}).get("currency", "USD")

        df = pd.DataFrame({
            "open": quote.get("open"),
            "high": quote.get("high"),
            "low": quote.get("low"),
            "close": quote.get("close"),
            "volume": quote.get("volume"),
        }, index=pd.to_datetime([
            datetime.fromtimestamp(t, tz=timezone.utc) for t in timestamps
        ]))
        df = df.dropna(subset=["close"])
        if df.empty:
            return {"error": f"No price data returned for {ticker}"}
        return {
            "df": df,
            "ticker": ticker.upper(),
            "currency": currency,
        }
    except httpx.HTTPStatusError as e:
        return {"error": f"Yahoo Finance HTTP {e.response.status_code} for {ticker}"}
    except (KeyError, IndexError, TypeError) as e:
        return {"error": f"Yahoo Finance parse error for {ticker}: {e}"}
    except httpx.RequestError as e:
        return {"error": f"Yahoo Finance request failed for {ticker}: {e}"}


# ── Composite analysis tool ─────────────────────────


@mcp.tool()
async def analyze_full(
    ticker: str,
    period: str = "1y",
) -> dict:
    """Full technical analysis — all indicators + composite signal in one call.

    Fetches prices from Yahoo Finance, computes via ta library:
    - SMA(200) trend filter (Layer 2)
    - EMA(50) secondary trend
    - RSI(14) entry/exit timing (Layer 3)
    - MACD(12,26,9) momentum (Layer 3)
    - Bollinger Bands(20,2) volatility (Layer 3)
    - Composite signal: strong_buy / hold / caution / wait / avoid

    ticker: stock/ETF/index/crypto symbol (AAPL, SPY, ^GSPC, BTC-USD).
    period: price history range (default 1y; use 2y for more SMA context).
    """
    prices = await _fetch_yahoo_ohlcv(ticker, period)
    if "error" in prices:
        return prices

    df = prices["df"]
    close = df["close"]
    n = len(close)

    result: dict = {
        "ticker": prices["ticker"],
        "currency": prices["currency"],
        "data_points": n,
        "date_range": f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
        "current_close": round(float(close.iloc[-1]), 4),
    }

    # SMA(200) — the #1 indicator from 114K backtests
    if n >= 200:
        sma200 = SMAIndicator(close, window=200).sma_indicator().iloc[-1]
        result["sma_200"] = round(float(sma200), 4)
        result["trend_signal"] = "bullish" if close.iloc[-1] > sma200 else "bearish"
    elif n >= 50:
        sma50 = SMAIndicator(close, window=50).sma_indicator().iloc[-1]
        result["sma_50"] = round(float(sma50), 4)
        result["trend_signal"] = "bullish" if close.iloc[-1] > sma50 else "bearish"
        result["trend_note"] = "Using SMA(50) — not enough data for SMA(200)"
    else:
        result["trend_signal"] = "insufficient_data"

    # EMA(50)
    if n >= 50:
        ema50 = EMAIndicator(close, window=50).ema_indicator().iloc[-1]
        result["ema_50"] = round(float(ema50), 4)

    # RSI(14)
    if n >= 15:
        rsi_val = RSIIndicator(close, window=14).rsi().iloc[-1]
        result["rsi_14"] = round(float(rsi_val), 2)
        if rsi_val < 30:
            result["rsi_signal"] = "oversold"
        elif rsi_val > 70:
            result["rsi_signal"] = "overbought"
        else:
            result["rsi_signal"] = "neutral"

    # MACD(12,26,9)
    if n >= 35:
        macd_ind = TAmacd(close, window_slow=26, window_fast=12, window_sign=9)
        result["macd"] = round(float(macd_ind.macd().iloc[-1]), 4)
        result["macd_signal_line"] = round(float(macd_ind.macd_signal().iloc[-1]), 4)
        result["macd_histogram"] = round(float(macd_ind.macd_diff().iloc[-1]), 4)
        result["macd_cross"] = "bullish" if result["macd"] > result["macd_signal_line"] else "bearish"

    # Bollinger Bands(20,2)
    if n >= 20:
        bb = BollingerBands(close, window=20, window_dev=2)
        result["bb_upper"] = round(float(bb.bollinger_hband().iloc[-1]), 4)
        result["bb_middle"] = round(float(bb.bollinger_mavg().iloc[-1]), 4)
        result["bb_lower"] = round(float(bb.bollinger_lband().iloc[-1]), 4)
        result["bb_bandwidth"] = round(float(bb.bollinger_wband().iloc[-1]), 6)
        price = close.iloc[-1]
        if price > result["bb_upper"]:
            result["bb_signal"] = "above_upper"
        elif price < result["bb_lower"]:
            result["bb_signal"] = "below_lower"
        else:
            result["bb_signal"] = "within_bands"

    # Composite signal (3-layer hierarchy from 114K backtests)
    if result.get("trend_signal") in ("bullish", "bearish") and "rsi_signal" in result:
        trend_ok = result["trend_signal"] == "bullish"
        rsi_sig = result["rsi_signal"]
        if trend_ok and rsi_sig == "oversold":
            result["composite"] = "strong_buy"
            result["advice"] = "Trend bullish + RSI oversold — high-probability buy zone."
        elif trend_ok and rsi_sig == "neutral":
            result["composite"] = "hold"
            result["advice"] = "Trend bullish, RSI neutral — hold or wait for pullback."
        elif trend_ok and rsi_sig == "overbought":
            result["composite"] = "caution"
            result["advice"] = "Trend bullish but RSI overbought — consider taking profits."
        elif not trend_ok and rsi_sig == "oversold":
            result["composite"] = "wait"
            result["advice"] = "RSI oversold but below SMA — potential bear trap, wait for trend confirmation."
        else:
            result["composite"] = "avoid"
            result["advice"] = "Below trend filter — stay out per 200-day SMA rule."

    return result


if __name__ == "__main__":
    mcp.run(transport="stdio")
