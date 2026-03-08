# 🏗️ MCP Trading & Forecasting Stack — Complete Inventory

> **Date:** 2026-02-28 | **Scope:** GitHub MCP servers for trading signals, prediction, analytics, and publishing
> **Legend:** 🪶 Lightweight (npx/uvx, no deps) · ⚙️ Medium (pip install, some deps) · 🐳 Heavy (Docker, DB, many deps) · ☁️ Cloud/SaaS

---

## 📊 Table of Contents

1. [Prediction Markets](#1-prediction-markets)
2. [Stock & Financial Data](#2-stock--financial-data)
3. [Crypto & On-Chain](#3-crypto--on-chain)
4. [Geopolitical Intelligence & Conflict](#4-geopolitical-intelligence--conflict)
5. [Shipping / Maritime / Logistics](#5-shipping--maritime--logistics)
6. [Flight Tracking](#6-flight-tracking)
7. [Satellite / Earth Observation](#7-satellite--earth-observation)
8. [Conferences / Events](#8-conferences--events)
9. [Academic Research & Tech Trends](#9-academic-research--tech-trends)
10. [Statistics & Calculation](#10-statistics--calculation)
11. [Social Media Publishing](#11-social-media-publishing)
12. [Predictive News Architecture](#12-predictive-news-architecture)
13. [Free Data Sources (No MCP Yet)](#13-free-data-sources-no-mcp-yet)
14. [Recommended Stacks](#14-recommended-stacks)

---

## 1. Prediction Markets

### Multi-Platform (Best Options)

| Repo | Lang | Platforms | Auth | Weight | Install |
|------|------|-----------|------|--------|---------|
| **[JamesANZ/prediction-market-mcp](https://github.com/JamesANZ/prediction-market-mcp)** | TS | Polymarket + PredictIt + Kalshi | ❌ None | 🪶 | `npx -y prediction-markets-mcp` |
| **[EricGrill/mcp-predictive-market](https://github.com/EricGrill/mcp-predictive-market)** | Py | 5 platforms (Poly+PredictIt+Kalshi+Manifold+Metaculus) | ❌ None | ⚙️ | pip |
| **[guzus/dr-manhattan](https://github.com/guzus/dr-manhattan)** | Py | 5+ exchanges (Poly+Kalshi+Limitless+Opinion+PredictFun) | 🔑 Per-exchange | ☁️ | Remote SSE |
| **[shaanmajid/prediction-mcp](https://github.com/shaanmajid/prediction-mcp)** | TS | Polymarket + Kalshi | 🔑 Kalshi optional | 🪶 | `npx -y prediction-mcp` |

### Polymarket-Only

| Repo | Lang | Features | Auth | Weight |
|------|------|----------|------|--------|
| **[kukapay/polymarket-predictions-mcp](https://github.com/kukapay/polymarket-predictions-mcp)** | Py | Simplest read-only | ❌ None | 🪶 |
| **[ozgureyilmaz/polymarket-mcp](https://github.com/ozgureyilmaz/polymarket-mcp)** | Rust | CLI + MCP, smart caching | ❌ None | ⚙️ |
| **[berlinbra/polymarket-mcp](https://github.com/berlinbra/polymarket-mcp)** | Py | Historical data (1d/7d/30d/all) | 🔑 Wallet | ⚙️ |
| **[caiovicentino/polymarket-mcp-server](https://github.com/caiovicentino/polymarket-mcp-server)** | Py | 🏆 Production trading: 45 tools, web dashboard, safety limits | 🔑 Wallet | 🐳 |
| **[lord5et/polymarket-mcp](https://github.com/lord5et/polymarket-mcp)** | TS | 40+ tools, trading optional | 🔑 Wallet optional | ⚙️ |
| **[PlayAINetwork/Polymarket-mcp](https://github.com/PlayAINetwork/Polymarket-mcp)** | TS | FOK/FAK/GTC orders, portfolio, P&L | 🔑 Wallet | ⚙️ |

### Other Markets

| Repo | Lang | Platform | Auth | Weight |
|------|------|----------|------|--------|
| **[bmorphism/manifold-mcp-server](https://github.com/bmorphism/manifold-mcp-server)** | TS | Manifold Markets (play money) | 🔑 API key | 🪶 |
| **[neur0map/polymaster](https://github.com/neur0map/polymaster)** | Py | Polymarket + Kalshi whale monitoring, anomaly detection | ❌ None | ⚙️ |

### 🏆 Pick

- **Zero-config read-only:** `JamesANZ/prediction-market-mcp` (npx one-liner)
- **Most platforms:** `dr-manhattan` (5+ exchanges, remote SSE)
- **Production trading:** `caiovicentino/polymarket-mcp-server` (safety limits, dashboard)
- **Arbitrage:** `EricGrill/mcp-predictive-market` (cross-platform)

---

## 2. Stock & Financial Data

### Multi-Provider

| Repo | Lang | Sources | Auth | Weight | Notes |
|------|------|---------|------|--------|-------|
| **[kiarashplusplus/FIML](https://github.com/kiarashplusplus/FIML)** | Py | 🏆 **17 providers**: Alpha Vantage, FMP, Polygon, Finnhub, Twelvedata, Tiingo, Intrinio, CCXT, CoinGecko, FRED, Quandl + more | 🔑 Mixed | 🐳 | Meta-layer, auto-fallback, Ray multi-agent, Redis+Postgres, compliance guardrails |
| **[wshobson/maverick-mcp](https://github.com/wshobson/maverick-mcp)** | Py | Yahoo Finance + Tiingo + FRED | ❌ Free | ⚙️ | 🏆 TA-Lib (20+ indicators), VectorBT backtest (15+ strategies), stock screening, portfolio optimization. Redis optional |
| **[leogue/StockMCP](https://github.com/leogue/stockmcp)** | Py | Yahoo Finance + Alpha Vantage | 🔑 AV free | ⚙️ | FastAPI, multi-source |

### Single-Source

| Repo | Lang | Source | Auth | Weight | Install |
|------|------|--------|------|--------|---------|
| **[Alex2Yang97/yahoo-finance-mcp](https://github.com/Alex2Yang97/yahoo-finance-mcp)** | Py | Yahoo Finance | ❌ None | 🪶 | pip |
| **[quartermaine/mcp-server-yahoo-finance](https://github.com/quartermaine/mcp-server-yahoo-finance)** | Py | Yahoo Finance + UI | ❌ None | ⚙️ | pip |
| **[AgentX-ai/yahoo-finance-server](https://github.com/AgentX-ai/yahoo-finance-server)** | TS | Yahoo Finance | ❌ None | 🪶 | npm |
| **[matteoantoci/mcp-alphavantage](https://github.com/matteoantoci/mcp-alphavantage)** | TS | Alpha Vantage | 🔑 Free key | 🪶 | npm |
| **[berlinbra/alpha-vantage-mcp](https://github.com/berlinbra/alpha-vantage-mcp)** | Py | Alpha Vantage | 🔑 Free key | 🪶 | pip |
| **[sverze/stock-market-mcp-server](https://github.com/sverze/stock-market-mcp-server)** | Py | Finnhub | 🔑 Free key | 🪶 | pip/uv |
| **[ferdousbhai/investor-agent](https://github.com/ferdousbhai/investor-agent)** | Py | Yahoo Finance | ❌ None | 🪶 | pip |

### Trading Execution

| Repo | Lang | Broker | Auth | Weight |
|------|------|--------|------|--------|
| **[ferdousbhai/tasty-agent](https://github.com/ferdousbhai/tasty-agent)** | Py | Tastytrade | 🔑 Account | ⚙️ |

### Strategy Platforms

| Repo | Lang | Features | Auth | Weight |
|------|------|----------|------|--------|
| **[QuantConnect/mcp-server](https://github.com/QuantConnect/mcp-server)** | Py | Official QC: create/compile/backtest/deploy live | 🔑 QC credentials (free tier) | 🐳 Docker |
| **[taylorwilsdon/quantconnect-mcp](https://github.com/taylorwilsdon/quantconnect-mcp)** | Py | QC + PCA, cointegration, mean-reversion, portfolio optimization | 🔑 QC credentials | ⚙️ `.dxt` one-click |

### 🏆 Pick

- **Enterprise multi-provider:** `FIML` (17 sources, auto-fallback, heavy)
- **All-in-one analysis:** `maverick-mcp` (TA-Lib + backtest + screening, medium weight)
- **Simplest free:** `yahoo-finance-mcp` (zero config)
- **Strategy lifecycle:** `taylorwilsdon/quantconnect-mcp` (research → backtest → live)

---

## 3. Crypto & On-Chain

| Repo | What | Auth | Weight |
|------|------|------|--------|
| **kukapay/whale-tracker-mcp** | Crypto whale transaction monitoring | ❌ None | 🪶 |
| **kukapay/crypto-feargreed-mcp** | Fear & Greed Index (real-time + historical) | ❌ None | 🪶 |
| **kukapay/dune-analytics-mcp** | On-chain analytics via Dune | 🔑 Dune API | 🪶 |
| **kukapay/cryptopanic-mcp-server** | Crypto news aggregation | 🔑 CryptoPanic | 🪶 |
| **mcpdotdirect/evm-mcp-server** | 30+ EVM blockchain interaction | ❌ None | ⚙️ |
| **Bankless/onchain-mcp** | Smart contract queries, transaction data | 🔑 Bankless API | 🪶 |
| **kukapay/pancakeswap-poolspy-mcp** | New pool tracking on PancakeSwap | ❌ None | 🪶 |

---

## 4. Geopolitical Intelligence & Conflict

| Repo | Lang | Sources | Auth | Weight | Notes |
|------|------|---------|------|--------|-------|
| **[kylezarif/mcp](https://github.com/kylezarif/mcp)** | Py | GDELT news/events + SEC EDGAR + macro data (Treasury/World Bank/ECB) + Stooq prices + FHFA housing | 🔑 Some free keys | ⚙️ | Multi-source intelligence in one server |
| **[koala73/worldmonitor](https://github.com/koala73/worldmonitor)** | TS | 24 sources: GDELT + ACLED + Polymarket + OpenSky + FRED + AIS + NASA FIRMS + cyber feeds | 🔑 Mixed | 🐳 | Dashboard (not MCP), but has clean adapters reusable as reference code |

### Gaps (No MCP wrapper)

| Source | Free? | Signal | Difficulty to Wrap |
|--------|-------|--------|-------------------|
| **ACLED** (conflict/protest/violence) | ✅ Free w/ registration | Geopolitical instability | ~100 lines |
| **IFES ElectionGuide** (global elections) | ✅ Free | Election date → volatility catalyst | ~60 lines |

---

## 5. Shipping / Maritime / Logistics

| Repo | Lang | Source | Auth | Weight | Signal |
|------|------|--------|------|--------|--------|
| **[Cyreslab-AI/marinetraffic-mcp-server](https://github.com/Cyreslab-AI/marinetraffic-mcp-server)** | TS | MarineTraffic API | 🔑 Paid | ⚙️ | Chokepoint monitoring, trade flow |
| **[idipankan/maersk-mcp](https://github.com/idipankan/maersk-mcp)** | — | Maersk schedules & deadlines | 🔑 Maersk API | 🪶 | Container ETA, schedule disruptions |
| **[tonybentley/signalk-mcp-server](https://github.com/tonybentley/signalk-mcp-server)** | TS | SignalK + AIS | 🔑 Local SignalK server | ⚙️ | V8 isolate, 97% token savings |

### Gaps

| Source | Free? | Signal | Difficulty |
|--------|-------|--------|-----------|
| **aisstream.io** (global AIS) | ✅ Free API key | Dark ships, chokepoint blockage | ~120 lines (WebSocket) |
| **UN Comtrade** (trade flows) | ✅ Free | Import/export volume shifts | ~100 lines |
| **Freightos** (container rates) | 💰 Paid | Freight cost signals | ~80 lines |

---

## 6. Flight Tracking

| Repo | Lang | Source | Auth | Weight |
|------|------|--------|------|--------|
| **[Cyreslab-AI/flightradar-mcp-server](https://github.com/Cyreslab-AI/flightradar-mcp-server)** | TS | AviationStack API | 🔑 API key | 🪶 |
| **[sunsetcoder/flightradar24-mcp-server](https://github.com/sunsetcoder/flightradar24-mcp-server)** | TS | Flightradar24 | 🔑 FR24 (paid) | 🪶 |

### Gap

| Source | Free? | Signal |
|--------|-------|--------|
| **OpenSky Network** | ✅ Free account | Military staging, private jet patterns |

---

## 7. Satellite / Earth Observation

| Repo | Lang | Source | Auth | Weight |
|------|------|--------|------|--------|
| **[cameronking4/google-earth-engine-mcp](https://github.com/cameronking4/google-earth-engine-mcp)** | TS | Google Earth Engine | 🔑 GEE account (free) | ⚙️ |
| **ProgramComputer/NASA-MCP-server** | — | NASA data sources | 🔑 NASA key (free) | ⚙️ |

### Free Satellite APIs (No MCP)

| Source | Signal | Difficulty |
|--------|--------|-----------|
| **Copernicus/Sentinel-2** | NDVI → crop yield, land use | Medium (~200 lines, geospatial libs) |
| **USDA WASDE/NASS** | Official crop estimates | Easy (~80 lines) |
| **NASA FIRMS** | Active fire → wildfire → commodity | Easy (~60 lines) |
| **NASA POWER** | Solar/weather → crop stress | Easy (~60 lines) |
| **NOAA Climate** | Drought/precip → agriculture | Easy (~80 lines) |

### Hedge Fund Use Cases (What Satellite Alpha Looks Like)

- NDVI time series → predict crop yields before USDA reports
- Parking lot car counts → estimate retail sales (Planet Labs, paid)
- Oil tank shadow analysis → crude inventory estimation
- Port activity from SAR → trade flow indicators
- Night light intensity → economic activity proxy

---

## 8. Conferences / Events

| Repo | Lang | Source | Auth | Weight |
|------|------|--------|------|--------|
| **[punkpeye/eventbrite-mcp](https://github.com/punkpeye/eventbrite-mcp)** | TS | Eventbrite | 🔑 OAuth/API | 🪶 |
| **vishalsachdev/eventbrite-mcp** | — | Eventbrite (alt) | 🔑 API | 🪶 |
| **ajeetraina/meetup-mcp-server** | — | Meetup.com | 🔑 API | 🪶 |
| **d4nshields/mcp-meetup** | — | Meetup (alt) | 🔑 API | 🪶 |
| **ajot/event-information-mcp-server** | — | Events via DigitalOcean AI | ☁️ | ☁️ |

### Gaps

No MCP for: Luma (popular AI events), confs.tech (tech conference JSON), CES/GDC/NeurIPS/SIGGRAPH scrapers

---

## 9. Academic Research & Tech Trends

### Academic Papers

| Repo | Lang | Sources | Auth | Weight | Install |
|------|------|---------|------|--------|---------|
| **[blazickjp/arxiv-mcp-server](https://github.com/blazickjp/arxiv-mcp-server)** | Py | arXiv search + download/read | ❌ None | 🪶 | `uv tool run arxiv-mcp-server` |
| **[anuj0456/arxiv-mcp-server](https://github.com/anuj0456/arxiv-mcp-server)** | Py | arXiv + citation analysis + trend tracking + export (BibTeX/RIS/JSON/CSV) | ❌ None | ⚙️ | pip |
| **[openags/paper-search-mcp](https://github.com/openags/paper-search-mcp)** | Py | 🏆 Multi: arXiv + PubMed + bioRxiv + Google Scholar + Semantic Scholar + IACR | ❌ None | ⚙️ | pip |
| **[zongmin-yu/semantic-scholar-fastmcp](https://github.com/zongmin-yu/semantic-scholar-fastmcp-mcp-server)** | Py | Semantic Scholar: papers, authors, citation networks | 🔑 Optional | 🪶 | pip |
| **[1Dark134/arxiv-mcp-server](https://github.com/1Dark134/arxiv-mcp-server)** | Py | Full arXiv: citation graphs, topic models, BibTeX, web UI | ❌ None | ⚙️ | pip |

### Tech Sentiment (Hacker News)

| Repo | Lang | Features | Auth | Weight | Install |
|------|------|----------|------|--------|---------|
| **[devabdultech/hn-mcp](https://github.com/devabdultech/hn-mcp)** | TS | HN via Algolia search | ❌ None | 🪶 | `npx -y @devabdultech/hn-mcp-server` |
| **[rawveg/hacker-news-mcp](https://github.com/rawveg/hacker-news-mcp)** | Py | HN + trend analysis + natural language search | ❌ None | ⚙️ | Docker available |
| **[erithwik/mcp-hn](https://github.com/erithwik/mcp-hn)** | TS | Top/new/ask/show + comments + search | ❌ None | 🪶 | npm |
| **[paabloLC/mcp-hacker-news](https://github.com/paabloLC/mcp-hacker-news)** | TS | Full HN API | ❌ None | 🪶 | `npx -y mcp-hacker-news` |

### Product Launches & Patents

| Repo | Lang | Source | Auth | Weight |
|------|------|--------|------|--------|
| **[jaipandya/producthunt-mcp-server](https://github.com/jaipandya/producthunt-mcp-server)** | Py | Product Hunt: posts, topics, votes, date filtering | 🔑 PH token | 🪶 |
| **[riemannzeta/patent_mcp_server](https://github.com/riemannzeta/patent_mcp_server)** | Py | USPTO patent data | ❌ Free | 🪶 |
| **[KunihiroS/google-patents-mcp](https://github.com/KunihiroS/google-patents-mcp)** | TS | Google Patents via SerpApi | 🔑 SerpApi key | 🪶 |

---

## 10. Statistics & Calculation

### Tier 1: Full Statistical Platforms

| Repo | Lang | Capabilities | Auth | Weight | Install |
|------|------|-------------|------|--------|---------|
| **[finite-sample/rmcp](https://github.com/finite-sample/rmcp)** | Py→R | 🏆 **429 R packages**: regression (OLS, logistic, panel, IV), ARIMA, **Bayesian (32 pkgs)**, **ML (61 pkgs)**, hypothesis testing, clustering, survival, **econometrics (55 pkgs)**, **time series (48 pkgs)**, inline ggplot2 | ❌ None | 🐳 R 4.4+ required | `pip install rmcp` |
| **[embeddedlayers/mcp-analytics](https://github.com/embeddedlayers/mcp-analytics)** | TS | **50+ tools**: regression, clustering, ARIMA, hypothesis testing, survival, Bayesian, NLP, reports | 🔑 API key | ☁️ Cloud-based | `npx -y mcp-remote@latest ...` |
| **[YuChenSSR/symbolica-mcp](https://github.com/YuChenSSR/symbolica-mcp)** | Py | **Full Python stack**: numpy, pandas, scipy, sklearn, sympy, matplotlib. Arbitrary code execution in Docker sandbox | ❌ None | 🐳 Docker | `docker run ychen94/computing-mcp` |

### Tier 2: Focused Statistical Analysis

| Repo | Lang | Capabilities | Auth | Weight | Install |
|------|------|-------------|------|--------|---------|
| **[mathpn/mcp-ols](https://github.com/mathpn/mcp-ols)** | Py | **Regression specialist**: OLS + logistic, patsy formulas, residual diagnostics (4-panel), VIF, Cook's distance, model comparison. CSV/Excel/JSON/Parquet/SQLite | ❌ None | 🪶 | `uvx mcp-ols` |
| **[quanticsoul4772/analytical-mcp](https://github.com/quanticsoul4772/analytical-mcp)** | TS | Dataset analysis, regression (linear/poly/logistic), hypothesis testing (t/χ²/ANOVA), viz specs, decision analysis, fallacy detection | ❌ None (Exa optional) | 🐳 Docker | Docker |
| **[jamie7893/statsource-mcp](https://github.com/jamie7893/statsource-mcp)** | Py | Stats on DB/CSV/API: mean, median, std, correlation, ML predictions, time series, groupby | 🔑 StatSource API | ☁️ | `uvx mcp-server-stats` |
| **[SepineTam/stata-mcp](https://github.com/SepineTam/stata-mcp)** | — | Stata regression + LLM integration | 🔑 Stata license | ⚙️ | macOS |

### Tier 3: Math & Computation

| Repo | Lang | Capabilities | Auth | Weight | Install |
|------|------|-------------|------|--------|---------|
| **[SHSharkar/MCP-Mathematics](https://github.com/SHSharkar/MCP-Mathematics)** | Py | **52 math functions**, 158 unit conversions (15 categories), financial calcs (NPV, IRR, amortization), AST-secure eval | ❌ None | 🪶 | `uv tool run mcp-mathematics` |
| **[huhabla/calculator-mcp-server](https://github.com/huhabla/calculator-mcp-server)** | Py | Stats (mean/median/mode/stdev), linear regression, matrix ops, trig | ❌ None | 🪶 | `uvx calculator-mcp-server` |
| **[EthanHenrickson/math-mcp](https://github.com/EthanHenrickson/math-mcp)** | TS | Arithmetic + basic stats (sum/mean/median/mode/min/max) + trig | ❌ None | 🪶 | Node |

### Tier 4: Wolfram Alpha / Symbolic

| Repo | Lang | Capabilities | Auth | Weight |
|------|------|-------------|------|--------|
| **[cnosuke/mcp-wolfram-alpha](https://github.com/cnosuke/mcp-wolfram-alpha)** | Go | High-precision computation, scientific data, step-by-step | 🔑 WA App ID (free 2000/mo) | 🪶 |
| **[paraporoco/Wolfram-MCP](https://github.com/paraporoco/Wolfram-MCP)** | Py | Full Wolfram Language: symbolic, calculus, stats | 🔑 Local Mathematica | 🐳 |
| **[Garoth/wolframalpha-llm-mcp](https://github.com/Garoth/wolframalpha-llm-mcp)** | TS | Simplest WA integration | 🔑 WA App ID | 🪶 |
| **[henryhawke/wolfram-llm-mcp](https://github.com/henryhawke/wolfram-llm-mcp)** | TS | Math, science, geographic, plots | 🔑 WA App ID | 🪶 |
| **[akalaric/mcp-wolframalpha](https://github.com/akalaric/mcp-wolframalpha)** | Py | WA + Gradio web UI | 🔑 WA App ID | ⚙️ |

### Tier 5: Trading-Specific Computation

| Repo | Lang | Capabilities | Auth | Weight |
|------|------|-------------|------|--------|
| **[wshobson/maverick-mcp](https://github.com/wshobson/maverick-mcp)** | Py | 🏆 **TA-Lib** (20+ indicators: SMA/EMA/RSI/MACD/Bollinger), **VectorBT** backtest (15+ strategies + ML), screening (Bullish/Bearish/Breakout), portfolio correlation/optimization, FRED macro | ❌ Free (Yahoo/Tiingo) | ⚙️ Redis optional |
| **[taylorwilsdon/quantconnect-mcp](https://github.com/taylorwilsdon/quantconnect-mcp)** | Py | PCA, Engle-Granger cointegration, mean-reversion, correlation, Huber portfolio optimization | 🔑 QC (free tier) | ⚙️ |
| **[QuantConnect/mcp-server](https://github.com/QuantConnect/mcp-server)** | Py | Official QC: create/compile/backtest/deploy live strategies | 🔑 QC credentials | 🐳 Docker |

### Tier 6: Data Analysis / Notebooks

| Repo | Lang | Capabilities | Auth | Weight |
|------|------|-------------|------|--------|
| **[kbsooo/jupythunder](https://github.com/kbsooo/jupythunder)** | Py | Claude ↔ Jupyter bridge (full scipy/pandas/sklearn) | ❌ None | ⚙️ |
| **JcXGTcW/wonderful_analysis_handler** | — | CSV + advanced stats + viz | ❌ None | ⚙️ |

### Tier 7: Forecasting Scoring

| Repo | Lang | Capabilities | Auth | Weight |
|------|------|-------------|------|--------|
| **[yhoiseth/python-prediction-scorer](https://github.com/yhoiseth/python-prediction-scorer)** | Py | Brier score, log score. Also REST API | ❌ None | 🪶 |
| **[openpredictionmarkets/socialpredict](https://github.com/openpredictionmarkets/socialpredict)** | Go+React | Self-hosted prediction market (BrierFoxForecast) | ❌ None | 🐳 |

### 🏆 Stats Pick by Use Case

| Need | Pick | Weight |
|------|------|--------|
| Full statistics | `rmcp` (429 R packages) | 🐳 |
| Quick regression | `mcp-ols` (`uvx mcp-ols`) | 🪶 |
| Trading analytics | `maverick-mcp` | ⚙️ |
| General math/units | `MCP-Mathematics` | 🪶 |
| Arbitrary Python | `symbolica-mcp` | 🐳 |
| High-precision symbolic | `cnosuke/mcp-wolfram-alpha` | 🪶 |
| Hypothesis testing | `rmcp` or `analytical-mcp` | 🐳/☁️ |
| Bayesian | `rmcp` (32 Bayesian packages) | 🐳 |
| Econometrics | `rmcp` (55 econometrics packages) | 🐳 |

---

## 11. Social Media Publishing

### Multi-Platform

| Repo | Lang | Platforms | Auth | Weight | Install |
|------|------|-----------|------|--------|---------|
| **[vanman2024/ayrshare-mcp](https://github.com/vanman2024/ayrshare-mcp)** | Py | 🏆 **13+**: Twitter, Reddit, LinkedIn, Instagram, TikTok, YouTube, Pinterest, Telegram, Threads, Bluesky, Snapchat, Google Business | 🔑 Ayrshare (paid) | ⚙️ | pip, FastMCP |
| **[Alemusica/social-cli-mcp](https://github.com/Alemusica/social-cli-mcp)** | TS | Twitter, Reddit, LinkedIn, Instagram | 🔑 Per-platform keys | 🪶 | npm |
| **[tayler-id/social-media-mcp](https://github.com/tayler-id/social-media-mcp)** | TS | Twitter, Mastodon, LinkedIn | 🔑 Per-platform + Brave/AI keys | ⚙️ | npm |
| **[shensi8312/blogburst-mcp-server](https://github.com/shensi8312/blogburst-mcp-server)** | TS | 9+ platforms + trending topics (HN/Reddit/Google Trends/PH) | 🔑 BlogBurst (free tier) | 🪶 | `npx -y blogburst-mcp-server` |

### Twitter/X

| Repo | Lang | Approach | Auth | Weight |
|------|------|----------|------|--------|
| **[taazkareem/twitter-mcp-server](https://github.com/taazkareem/twitter-mcp-server)** | TS | `agent-twitter-client` lib | 🔑 Twitter creds | 🪶 |
| **[Barresider/x-mcp](https://github.com/Barresider/x-mcp)** | TS | Playwright automation (no official API) | 🔑 Twitter login | ⚙️ |
| **[crazyrabbitLTC/mcp-twitter-server](https://github.com/crazyrabbitLTC/mcp-twitter-server)** | TS | Official API + SocialData.tools | 🔑 Twitter API + optional SocialData | ⚙️ |
| **[EnesCinr/twitter-mcp](https://github.com/EnesCinr/twitter-mcp)** | TS | Official API | 🔑 Twitter API | 🪶 `npx -y @enescinar/twitter-mcp` |
| **LuniaKunal/mcp-twitter** | TS | Official API | 🔑 Twitter API | 🪶 |

### Reddit

| Repo | Lang | Features | Auth | Weight |
|------|------|----------|------|--------|
| **[Hawstein/mcp-server-reddit](https://github.com/Hawstein/mcp-server-reddit)** | Py | Read-only: frontpage, hot/new/top/rising, comments | ❌ None (public API) | 🪶 `uvx mcp-server-reddit` |
| **saginawj/mcp-reddit-companion** | — | Custom curated feeds + analysis | 🔑 Reddit API | ⚙️ |
| **GridfireAI/reddit-mcp** | — | Browse, search, read | ❌ None | 🪶 |

### Other Platforms

| Repo | Platform | Weight |
|------|----------|--------|
| **LT-aitools/MCPblusky** | Bluesky / ATProtocol | 🪶 |
| **berlinbra/BlueSky-MCP** | Bluesky profiles + social graph | 🪶 |
| **zhangzhongnan928/mcp-warpcast-server** | Warpcast (Farcaster) | 🪶 |
| **tiroshanm/facebook-mcp-server** | Facebook Page management | ⚙️ |

### ⚠️ Legal Best Practices for Trading Sentiment Posts

- ✅ Always disclose positions held ("I hold $X")
- ✅ Mark AI-assisted content as AI-generated
- ✅ One account = one voice = legitimate expression
- ❌ No identical posts across many accounts (looks like coordination)
- ❌ No purchased engagement (fake likes/retweets)
- ❌ No impersonation or fake personas

---

## 12. Predictive News Architecture

**Concept:** AI generates probabilistic predictions → publishes with timestamps → auto-resolves against reality → scores itself with Brier scores → publishes accountability scorecard.

**Nothing like this exists as an integrated product. All building blocks available.**

### Components

| Role | Tool | Weight |
|------|------|--------|
| **Prediction model** | [OpenForecaster](https://openforecaster.github.io/) (8B, trained on 52k questions, competitive Brier score) | 🐳 |
| **Scoring** | `yhoiseth/python-prediction-scorer` (Brier + log score) | 🪶 |
| **Self-hosted market** | `openpredictionmarkets/socialpredict` (BrierFoxForecast) | 🐳 |
| **Signal feeds** | `kylezarif/mcp` (GDELT) + `hn-mcp` + `arxiv-mcp` + prediction markets | 🪶–⚙️ |
| **Reality check** | web_search + GDELT + market resolution APIs | 🪶 |
| **Publishing** | `blogburst-mcp` or `social-cli-mcp` | 🪶 |

### Pipeline

```
Signal Ingestion (cron) → Prediction Engine (OpenForecaster / Claude API)
  → Prediction Store (MongoDB)
    → Publish (static site / RSS / social) [⚠️ AI PREDICTION label]
    → Resolution Checker (cron, daily: web_search + GDELT)
      → Brier Score computation
        → Public Scorecard (calibration curve, hit/miss by category)
```

### MVP Estimate

~500 lines Python + HTML template. Claude API with structured prompts gets 80% of OpenForecaster quality.

### Legal (Germany/EU)

- Mark as AI-generated per EU AI Act
- Don't frame as investment advice
- GDPR compliance for user data

---

## 13. Free Data Sources (No MCP Yet)

### High Priority Wrapping Targets

| # | Source | Free? | Signal | MCP Lines | Priority |
|---|--------|-------|--------|-----------|----------|
| 1 | **ACLED** (conflict/protest) | ✅ Registration | Geopolitical instability | ~100 | 🔴 |
| 2 | **aisstream.io** (global AIS) | ✅ Free key | Chokepoint, dark ships | ~120 (WebSocket) | 🔴 |
| 3 | **OpenSky Network** (flights) | ✅ Free account | Military staging | ~80 | 🔴 |
| 4 | **IFES ElectionGuide** (elections) | ✅ Free | Election timing → vol | ~60 | 🔴 |
| 5 | **FRED standalone** (US macro) | ✅ Free key | Yield curve, CPI, M2 | ~80 | 🔴 |
| 6 | **USDA WASDE/NASS** (crop reports) | ✅ Free | Crop yield prediction | ~80 | 🔴 |
| 7 | **NASA FIRMS** (fires) | ✅ Free | Wildfire → commodity | ~60 | 🟡 |
| 8 | **NOAA weather/drought** | ✅ Free | Agriculture + energy | ~80 | 🟡 |
| 9 | **Google Trends** | ✅ Unofficial | Consumer demand proxy | ~100 | 🟡 |
| 10 | **UN Comtrade** (trade flows) | ✅ Free | Import/export shifts | ~100 | 🟡 |
| 11 | **confs.tech** (tech conferences) | ✅ Free JSON | Product launch timing | ~40 | 🟢 |
| 12 | **CoinGecko** (crypto) | ✅ Free | Market cap/volume/sentiment | ~80 | 🟢 |

---

## 14. Recommended Stacks

### 🏁 Zero-Config Starter (No API Keys)

```json
{
  "predictions":  "npx -y prediction-markets-mcp",
  "hackernews":   "npx -y @devabdultech/hn-mcp-server",
  "arxiv":        "uv tool run arxiv-mcp-server",
  "math":         "uv tool run mcp-mathematics",
  "regression":   "uvx mcp-ols",
  "calculator":   "uvx calculator-mcp-server",
  "reddit_read":  "uvx mcp-server-reddit"
}
```

**Weight:** All 🪶 lightweight. No Docker, no DB, no paid keys.

### ⚙️ Free-Registration Tier

Add to starter with free API keys:

| MCP | What You Get | Key Source |
|-----|-------------|-----------|
| `maverick-mcp` | TA-Lib + VectorBT + screening | Yahoo free, Tiingo free |
| `quantconnect-mcp` | Backtest → live deploy | QC free tier |
| `kylezarif/mcp` | GDELT + SEC EDGAR + macro | Some free keys |
| `cnosuke/mcp-wolfram-alpha` | High-precision computation | WA free (2000/mo) |
| `semantic-scholar-mcp` | Citation networks | Optional key |

### 🐳 Full Production Stack

| Layer | MCP(s) | Weight |
|-------|--------|--------|
| **Market data** | `FIML` (17 providers, auto-fallback) | 🐳 |
| **Predictions** | `dr-manhattan` (5+ exchanges) | ☁️ |
| **Intelligence** | `kylezarif/mcp` + ACLED wrapper | ⚙️ |
| **Statistics** | `rmcp` (429 R packages) | 🐳 |
| **Trading analysis** | `maverick-mcp` | ⚙️ |
| **Strategy** | `quantconnect-mcp` | ⚙️ |
| **Publishing** | `ayrshare-mcp` (13 platforms) | ⚙️ |
| **Scoring** | `python-prediction-scorer` | 🪶 |

### 📡 Signal Coverage Matrix

| Domain | Read | Analyze | Act |
|--------|------|---------|-----|
| **Prediction markets** | ✅ `prediction-market-mcp` | ✅ `maverick-mcp` | ✅ `polymarket-mcp-server` |
| **Stocks** | ✅ `yahoo-finance-mcp` | ✅ `maverick-mcp` | ✅ `tasty-agent` |
| **Crypto** | ✅ `crypto-feargreed` | ✅ `FIML` | ✅ `evm-mcp-server` |
| **Geopolitical** | ✅ `kylezarif/mcp` | ✅ `rmcp` | ⚠️ Manual |
| **Shipping** | ⚠️ `marinetraffic` (paid) | ✅ `rmcp` | ⚠️ Manual |
| **Weather/Crops** | ⚠️ No MCP | ✅ `rmcp` | ⚠️ Manual |
| **Research** | ✅ `arxiv-mcp` | ✅ `paper-search-mcp` | ⚠️ Manual |
| **Tech trends** | ✅ `hn-mcp` | ✅ `blogburst-mcp` | ✅ `social-cli-mcp` |
| **Social sentiment** | ✅ `twitter-mcp` + `reddit-mcp` | ✅ `analytical-mcp` | ✅ `ayrshare-mcp` |

---

## Weight Classification Guide

| Symbol | Meaning | Typical Setup | RAM | Dependencies |
|--------|---------|---------------|-----|-------------|
| 🪶 | **Lightweight** | `npx`/`uvx` one-liner | <100MB | Minimal (SDK + HTTP client) |
| ⚙️ | **Medium** | `pip install` + config | 100-500MB | Python libs (pandas, TA-Lib, etc.) |
| 🐳 | **Heavy** | Docker / DB / multi-service | 500MB-2GB+ | R runtime, Redis, Postgres, Docker |
| ☁️ | **Cloud/SaaS** | API key to remote service | ~0 local | Network dependency, potential cost |

### Weight vs. Capability Tradeoff

```
Capability ──────────────────────────────────►
    │
    │  🪶 prediction-market-mcp     ⚙️ maverick-mcp        🐳 FIML
    │  🪶 mcp-ols                   ⚙️ quantconnect-mcp    🐳 rmcp (429 pkgs)
    │  🪶 MCP-Mathematics           ⚙️ analytical-mcp      🐳 symbolica-mcp
    │  🪶 hn-mcp                    ⚙️ ayrshare-mcp        ☁️ mcp-analytics
    │
Setup Effort ────────────────────────────────►
```

**Rule of thumb:** Start 🪶, add ⚙️ when you hit limits, go 🐳 only for production.

---

*Generated 2026-02-28. Sources: GitHub repositories, npm/PyPI packages, project READMEs.*
*All repositories are open source unless noted. Auth requirements may change.*
