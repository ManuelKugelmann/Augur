# MCP Server Inventory for Situational Forecasting & Trading

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    STRATEGY LAYER                            │
│  QuantConnect MCP │ Wolfram MCP │ MCP-Mathematics           │
│  (backtest+deploy)  (computation)  (52 math functions)      │
├─────────────────────────────────────────────────────────────┤
│                  SIGNAL GENERATION                           │
│  Prediction Markets │ Whale Alerts │ Sentiment │ Patents    │
├─────────────────────────────────────────────────────────────┤
│                  BACKGROUND DATA                             │
│  Macro │ Geopolitical │ Shipping │ Flights │ Events │ Tech  │
├─────────────────────────────────────────────────────────────┤
│                  RESEARCH LAYER                              │
│  arXiv │ Semantic Scholar │ Hacker News │ Product Hunt      │
└─────────────────────────────────────────────────────────────┘
```

---

## 1. PREDICTION MARKETS

### ✅ Multi-Platform (Best Options)

| Repo | Lang | Platforms | Auth | Install |
|------|------|-----------|------|---------|
| **[JamesANZ/prediction-market-mcp](https://github.com/JamesANZ/prediction-market-mcp)** | TS | Polymarket + PredictIt + Kalshi | ❌ None | `npx -y prediction-markets-mcp` |
| **[EricGrill/mcp-predictive-market](https://github.com/EricGrill/mcp-predictive-market)** | Py | Poly + PredictIt + Kalshi + Manifold + Metaculus | ⚠️ Varies | Cross-platform arbitrage detection |
| **[guzus/dr-manhattan](https://github.com/guzus/dr-manhattan)** | Py | Poly + Kalshi + Limitless + Opinion + PredictFun | ⚠️ Per-exchange | "CCXT for prediction markets", remote SSE |
| **[shaanmajid/prediction-mcp](https://github.com/shaanmajid/prediction-mcp)** | TS | Polymarket + Kalshi | ⚠️ Kalshi optional | Full-text search <1ms, orderbooks |

### ✅ Polymarket-Only (9 implementations)

| Repo | Best for | Auth |
|------|----------|------|
| **[kukapay/polymarket-predictions-mcp](https://github.com/kukapay/polymarket-predictions-mcp)** | 🏆 Simplest read-only | ❌ None |
| **[ozgureyilmaz/polymarket-mcp](https://github.com/ozgureyilmaz/polymarket-mcp)** | Rust, smart caching, CLI | ❌ None |
| **[berlinbra/polymarket-mcp](https://github.com/berlinbra/polymarket-mcp)** | Historical data (1d/7d/30d) | 🔑 Wallet |
| **[caiovicentino/polymarket-mcp-server](https://github.com/caiovicentino/polymarket-mcp-server)** | 🏆 Production trading (45 tools, safety limits) | 🔑 Wallet |
| **[lord5et/polymarket-mcp](https://github.com/lord5et/polymarket-mcp)** | 40+ tools incl. trading | ⚠️ Optional |
| **[PlayAINetwork/Polymarket-mcp](https://github.com/PlayAINetwork/Polymarket-mcp)** | FOK/FAK/GTC orders, P&L | 🔑 Wallet |

### ✅ Other Markets

| Repo | Platform | Auth |
|------|----------|------|
| **[bmorphism/manifold-mcp-server](https://github.com/bmorphism/manifold-mcp-server)** | Manifold Markets (complete API) | 🔑 API key |

### ✅ Whale Monitoring

| Repo | What | Auth |
|------|------|------|
| **[neur0map/polymaster](https://github.com/neur0map/polymaster)** | Polymarket + Kalshi whale tx, anomaly detection, MCP scoring | N/A |

### 🏆 Recommendations
- **Zero-config read-only**: `JamesANZ/prediction-market-mcp` — `npx` one-liner, no keys
- **Most platforms**: `dr-manhattan` — 5+ exchanges, unified API
- **Production trading**: `caiovicentino/polymarket-mcp-server` — safety limits, web dashboard
- **Arbitrage detection**: `EricGrill/mcp-predictive-market` — cross-platform unified models

---

## 2. GEOPOLITICAL INTELLIGENCE & CONFLICT

| Repo | Data Source | Auth | Status |
|------|------------|------|--------|
| **[kylezarif/mcp](https://github.com/kylezarif/mcp)** → `gdelt_news.py` | GDELT news/events + SEC EDGAR + macro (Treasury/WorldBank/ECB) + Stooq prices | Mixed | ✅ MCP |
| **[koala73/worldmonitor](https://github.com/koala73/worldmonitor)** | 24 sources: GDELT + ACLED + Polymarket + OpenSky + FRED + AIS + NASA FIRMS + cyber feeds | N/A | ❌ Dashboard (has clean adapters) |

### ❌ Gaps
- **ACLED** (Armed Conflict Location & Event Data) — free API with registration, no MCP wrapper
- **Election calendar** — IFES ElectionGuide API + `electioncal/us` JSON exist, no MCP wrapper

---

## 3. SHIPPING / MARITIME / LOGISTICS

| Repo | Data Source | Auth | Signal |
|------|------------|------|--------|
| **[Cyreslab-AI/marinetraffic-mcp-server](https://github.com/Cyreslab-AI/marinetraffic-mcp-server)** | MarineTraffic vessel positions/details/area | 🔑 API key (paid) | Chokepoint disruptions |
| **[idipankan/maersk-mcp](https://github.com/idipankan/maersk-mcp)** | Maersk vessel schedules & deadlines | 🔑 Maersk API | Container ETAs |
| **[tonybentley/signalk-mcp-server](https://github.com/tonybentley/signalk-mcp-server)** | SignalK + AIS targets, V8 isolate | Local server | Own vessel + nearby |

### Free APIs (no MCP wrapper yet)
- **[aisstream.io](https://aisstream.io)** — free WebSocket global AIS data, MMSI filtering
- **UN Comtrade** — free trade flow data (import/export volumes by country/commodity)

---

## 4. FLIGHT TRACKING

| Repo | Data Source | Auth |
|------|------------|------|
| **[Cyreslab-AI/flightradar-mcp-server](https://github.com/Cyreslab-AI/flightradar-mcp-server)** | AviationStack API | 🔑 API key |
| **[sunsetcoder/flightradar24-mcp-server](https://github.com/sunsetcoder/flightradar24-mcp-server)** | Flightradar24 | 🔑 FR24 key (paid) |

### Free API (no MCP wrapper)
- **OpenSky Network** — free REST API, ~12s delay without account, global coverage

---

## 5. CONFERENCES / EVENTS / MEETUPS

| Repo | Platform | Auth |
|------|----------|------|
| **[punkpeye/eventbrite-mcp](https://github.com/punkpeye/eventbrite-mcp)** | Eventbrite | 🔑 OAuth |
| **[vishalsachdev/eventbrite-mcp](https://github.com/vishalsachdev/eventbrite-mcp)** | Eventbrite (alt) | 🔑 |
| **[ajeetraina/meetup-mcp-server](https://github.com/ajeetraina/meetup-mcp-server)** | Meetup.com | 🔑 |
| **[d4nshields/mcp-meetup](https://github.com/d4nshields/mcp-meetup)** | Meetup (alt) | 🔑 |
| **[ajot/event-information-mcp-server](https://github.com/ajot/event-information-mcp-server)** | Events via DO Gradient AI | 🔑 |

### ❌ Gaps: No Luma, no confs.tech, no major conference schedule MCPs

---

## 6. EMERGING TECH / RESEARCH / INNOVATION SIGNALS

### Academic Papers

| Repo | Sources | Auth | Best for |
|------|---------|------|----------|
| **[blazickjp/arxiv-mcp-server](https://github.com/blazickjp/arxiv-mcp-server)** | arXiv | ❌ None | 🏆 Simplest: search, download, read |
| **[anuj0456/arxiv-mcp-server](https://github.com/anuj0456/arxiv-mcp-server)** | arXiv | ❌ None | Citation analysis, trend tracking |
| **[openags/paper-search-mcp](https://github.com/openags/paper-search-mcp)** | arXiv + PubMed + bioRxiv + Google Scholar + Semantic Scholar + IACR | ⚠️ Optional | 🏆 Multi-source research |
| **[zongmin-yu/semantic-scholar-fastmcp-mcp-server](https://github.com/zongmin-yu/semantic-scholar-fastmcp-mcp-server)** | Semantic Scholar | ⚠️ Optional | Citation networks, author profiles |
| **[shoumikdc/arXiv-mcp](https://github.com/shoumikdc/arXiv-mcp)** | arXiv RSS | ❌ None | Daily new paper alerts by category |

### Tech Sentiment & Trends

| Repo | Source | Auth | Best for |
|------|--------|------|----------|
| **[devabdultech/hn-mcp](https://github.com/devabdultech/hn-mcp)** | Hacker News + Algolia | ❌ None | 🏆 `npx -y @devabdultech/hn-mcp-server` |
| **[rawveg/hacker-news-mcp](https://github.com/rawveg/hacker-news-mcp)** | HN + trend analysis | ❌ None | Trend analysis, NL title search |
| **[erithwik/mcp-hn](https://github.com/erithwik/mcp-hn)** | HN top/new/ask/show | ❌ None | Simple stories + comments |
| **[jaipandya/producthunt-mcp-server](https://github.com/jaipandya/producthunt-mcp-server)** | Product Hunt | 🔑 PH token | Startup/product launch signals |

### Patents / IP

| Repo | Source | Auth |
|------|--------|------|
| **[riemannzeta/patent_mcp_server](https://github.com/riemannzeta/patent_mcp_server)** | USPTO (FastMCP) | ❌ Free |
| **[KunihiroS/google-patents-mcp](https://github.com/KunihiroS/google-patents-mcp)** | Google Patents via SerpApi | 🔑 SerpApi key |

---

## 7. MACRO / FINANCIAL DATA

| Repo | Sources | Auth |
|------|---------|------|
| **[kylezarif/mcp](https://github.com/kylezarif/mcp)** | GDELT + SEC EDGAR + Treasury yields + World Bank + ECB + Stooq prices + FHFA housing | Mixed |

### Free APIs (no standalone MCP)
- **FRED** (Federal Reserve Economic Data) — free API, massive macro dataset
- **World Bank Open Data** — free, global development indicators
- **Yahoo Finance** (via yfinance) — free historical OHLCV
- **Alpha Vantage** — free tier (25 calls/day), stocks + forex + crypto
- **CoinGecko** — free crypto data

---

## 8. CALCULATION & STATISTICS MCPs

### 🔢 General Math / Computation

| Repo | Lang | What | Auth |
|------|------|------|------|
| **[SHSharkar/MCP-Mathematics](https://github.com/SHSharkar/MCP-Mathematics)** | Py | 🏆 **52 math functions, 158 unit conversions, financial calcs**, AST-safe eval | ❌ None |
| **[paraporoco/Wolfram-MCP](https://github.com/paraporoco/Wolfram-MCP)** | Py | Wolfram Language: equations, calculus, stats. Needs local Mathematica | 🔑 Local install |
| **[cnosuke/mcp-wolfram-alpha](https://github.com/cnosuke/mcp-wolfram-alpha)** | Go | Wolfram Alpha API: high-precision computation, scientific data | 🔑 WA App ID (free tier) |
| **[Garoth/wolframalpha-llm-mcp](https://github.com/Garoth/wolframalpha-llm-mcp)** | TS | Wolfram Alpha LLM API — simplest WA integration | 🔑 WA App ID |
| **[henryhawke/wolfram-llm-mcp](https://github.com/henryhawke/wolfram-llm-mcp)** | TS | WA: math, science, geographic, data analysis, plots | 🔑 WA App ID |
| **[akalaric/mcp-wolframalpha](https://github.com/akalaric/mcp-wolframalpha)** | Py | WA + Gradio web UI | 🔑 WA App ID |
| **[huhabla/calculator-mcp-server](https://github.com/huhabla/calculator-mcp-server)** | ? | Advanced math calculations for Claude | ❌ None |

### 📈 Trading-Specific Computation

| Repo | Lang | What | Auth |
|------|------|------|------|
| **[wshobson/maverick-mcp](https://github.com/wshobson/maverick-mcp)** | Py | 🏆 **Full trading analysis suite**: TA-Lib (20+ indicators), VectorBT backtesting (15+ strategies), stock screening (Maverick Bullish/Bearish), portfolio optimization, correlation, FRED macro, earnings. Redis caching, multi-transport | ❌ None (free data via Tiingo/Yahoo) |
| **[QuantConnect/mcp-server](https://github.com/QuantConnect/mcp-server)** | Py | 🏆 **Official QC MCP**: create/compile/backtest/deploy live strategies, historical data, project mgmt | 🔑 QC user ID + API token (free tier) |
| **[taylorwilsdon/quantconnect-mcp](https://github.com/taylorwilsdon/quantconnect-mcp)** | Py | QC + advanced analytics: PCA, Engle-Granger cointegration, mean-reversion, portfolio optimization. `.dxt` desktop extension | 🔑 QC creds (free tier) |

### 🏆 Recommendations for Computation Stack
1. **Quick math/stats**: `MCP-Mathematics` — zero deps, 52 functions, unit conversions
2. **High-precision/symbolic**: `cnosuke/mcp-wolfram-alpha` — free WA tier (2000 calls/month)
3. **Technical analysis**: `maverick-mcp` — TA-Lib + VectorBT + screening in one server
4. **Full strategy lifecycle**: `taylorwilsdon/quantconnect-mcp` — research → backtest → live deploy

---

## 9. BEST FREE DATA SOURCES (No API Key Required)

| Source | Data | Access | Trading Signal |
|--------|------|--------|----------------|
| **Polymarket/PredictIt/Kalshi** | Prediction odds | ✅ Via `prediction-market-mcp` | Event probability pricing |
| **arXiv** | Research papers | ✅ Via `arxiv-mcp-server` | Breakthrough detection |
| **Hacker News** | Tech discussion/sentiment | ✅ Via `hn-mcp` | Tech trend momentum |
| **USPTO** | Patent filings | ✅ Via `patent_mcp_server` | Competitive intel |
| **GDELT** | Global news/events | ✅ Via `kylezarif/mcp` | Geopolitical risk |
| **Yahoo Finance** | OHLCV, fundamentals | ✅ Via `maverick-mcp` | Price/volume data |
| **FRED** | US macro indicators | ✅ Via `maverick-mcp` | Macro regime |
| **aisstream.io** | Global vessel AIS | Free API key, ❌ no MCP | Supply chain disruption |
| **OpenSky Network** | Flight tracking | Free account, ❌ no MCP | Military/private patterns |
| **ACLED** | Conflict/protest data | Free registration, ❌ no MCP | Political instability |
| **IFES ElectionGuide** | Global election dates | Free, ❌ no MCP | Election event timing |
| **UN Comtrade** | Trade flows | Free, ❌ no MCP | Import/export shifts |
| **Semantic Scholar** | Citations/impact | ⚠️ Via `semantic-scholar-mcp` | Research momentum |
| **confs.tech** | Tech conference dates | Free JSON, ❌ no MCP | Product launch timing |
| **World Bank** | Global macro/dev | Free, partial via `kylezarif/mcp` | EM risk indicators |

---

## 10. KEY GAPS TO WRAP IN FastMCP

### 🔴 High Priority (High signal value, free APIs, easy to wrap)

| Gap | Free API | ~Lines | Signal Value | Reference Code |
|-----|----------|--------|-------------|----------------|
| **ACLED** (conflict/protest/violence) | ✅ Free w/ registration | ~80 | Geopolitical instability, regime risk | `worldmonitor` has adapter |
| **FRED** (standalone macro indicators) | ✅ Free API key | ~100 | Yield curve, unemployment, CPI, M2 | `maverick-mcp` has partial |
| **aisstream.io** (global AIS vessel) | ✅ Free API key | ~120 | Chokepoint blockage, dark ships, trade disruption | WebSocket → MCP adapter |
| **IFES ElectionGuide** (global elections) | ✅ Free | ~60 | Election date → volatility catalyst | Python package exists |
| **OpenSky Network** (free flights) | ✅ Free account | ~80 | Military staging, private jet patterns | REST API, well documented |

### 🟡 Medium Priority

| Gap | Free API | ~Lines | Signal Value |
|-----|----------|--------|-------------|
| **UN Comtrade** (trade flows) | ✅ Free | ~100 | Import/export volume shifts by commodity |
| **confs.tech** (tech conference calendar) | ✅ Free JSON | ~40 | Product launch correlation, sector attention |
| **Alpha Vantage** (stocks/forex/crypto) | ✅ Free tier (25/day) | ~80 | Supplementary price data |
| **CoinGecko** (crypto market data) | ✅ Free | ~80 | Crypto market cap, volume, sentiment |
| **TradingView chart snapshots** | Free (scraping) | ~100 | Visual TA sharing |

### 🟢 Nice-to-Have

| Gap | Notes |
|-----|-------|
| **Luma events** | No official API, scraper needed |
| **GitHub Trending** | Scrape trending repos for tech signals |
| **Reddit sentiment** | Via Pushshift/Reddit API, several libs exist |
| **NOAA weather** | Free API, commodity trading correlation |
| **Earthquake/USGS** | Free API, insurance/reinsurance signals |

---

## 11. COMPLETE ZERO-CONFIG STARTER STACK

Minimum viable setup requiring **zero API keys**:

```json
{
  "mcpServers": {
    "predictions": {
      "command": "npx", "args": ["-y", "prediction-markets-mcp"]
    },
    "hackernews": {
      "command": "npx", "args": ["-y", "@devabdultech/hn-mcp-server"]
    },
    "arxiv": {
      "command": "uv", "args": ["tool", "run", "arxiv-mcp-server"]
    },
    "math": {
      "command": "uv", "args": ["tool", "run", "mcp-mathematics"]
    }
  }
}
```

**Adds with free registration/keys:**

```json
{
  "patents":       "riemannzeta/patent_mcp_server → USPTO",
  "wolfram":       "cnosuke/mcp-wolfram-alpha → WA free tier (2000/mo)",
  "quantconnect":  "uvx quantconnect-mcp → backtest + deploy",
  "maverick":      "wshobson/maverick-mcp → TA-Lib + VectorBT + screening",
  "gdelt":         "kylezarif/mcp → gdelt_news.py + SEC + macro",
  "semanticscholar": "zongmin-yu/semantic-scholar-fastmcp → citations"
}
```

---

## 12. SIGNAL CORRELATION MAP

```
MACRO REGIME (FRED, World Bank, ECB)
  │
  ├─→ GEOPOLITICAL RISK (GDELT + ACLED + Elections)
  │     │
  │     ├─→ SUPPLY CHAIN (AIS vessels + container rates)
  │     │     └─→ COMMODITY IMPACT
  │     │
  │     └─→ PREDICTION MARKETS (event probability)
  │           └─→ WHALE ALERTS (smart money flow)
  │
  ├─→ TECH DISRUPTION (arXiv + HN + Patents + Product Hunt)
  │     └─→ SECTOR ROTATION signals
  │
  └─→ EVENT CATALYSTS (Conferences + Elections + Earnings)
        └─→ VOLATILITY WINDOWS
              │
              ▼
        STRATEGY EXECUTION
        (QuantConnect backtest → live deploy)
        (Maverick TA screening → entry/exit)
        (Wolfram/Math → position sizing)
```
