# MCP Tools Review — Consolidation & Provider-Agnostic Routing

**Date**: 2026-03-07
**Scope**: All 10 FastMCP sub-servers (store + 9 data domains) + 3 utility MCPs

---

## Executive Summary

The trading stack exposes **50+ tools** across 10 namespaces via a single combined FastMCP process, plus 1 utility MCP (filesystem) via stdio. All servers are **self-hosted** — no cloud MCP services.

This review identifies:
1. **4 redundant tools** that wrap the same API endpoint or duplicate existing capability
2. **3 provider-agnostic routing opportunities** where multiple tools query different providers for the same concept
3. **2 utility MCP consolidation candidates** (optional, low priority)

---

## 1. Redundant Tools (Remove or Merge)

### 1.1 ReliefWeb Duplication — CRITICAL

| Tool | Server | Endpoint | Difference |
|------|--------|----------|------------|
| `conflict_reliefweb_reports` | conflict_server.py:95 | `POST api.reliefweb.int/v1/reports` | Generic query + country filter |
| `politics_election_reports` | elections_server.py:140 | `GET api.reliefweb.int/v1/reports` | Hardcoded `query="election"` |

**Same API, same data.** The elections variant just pre-fills `query="election"`. Users can already call `conflict_reliefweb_reports(query="election")` for identical results.

**Action**: Remove `politics_election_reports` from `elections_server.py`.

### 1.2 Military Spending Wrapper — LOW

| Tool | Server | Endpoint |
|------|--------|----------|
| `conflict_military_spending` | conflict_server.py:56 | `api.worldbank.org/.../MS.MIL.XPND.GD.ZS` |
| `econ_worldbank_indicator` | macro_server.py:41 | `api.worldbank.org/.../indicator/{indicator}` |

`military_spending(country, date)` is literally `worldbank_indicator(indicator="MS.MIL.XPND.GD.ZS", country, date)` with the indicator hardcoded. It's a convenience alias that adds tool surface area without adding capability.

**Action**: Remove `military_spending`. Document `MS.MIL.XPND.GD.ZS` as an example in `worldbank_indicator`'s docstring.

### 1.3 Earthquake Overlap — MEDIUM

| Tool | Server | Source | Scope |
|------|--------|--------|-------|
| `disaster_get_earthquakes` | disasters_server.py:10 | USGS | Earthquakes only, detailed (magnitude, alert, tsunami) |
| `disaster_get_disasters` | disasters_server.py:33 | GDACS | All disasters incl. earthquakes (lower detail) |
| `disaster_get_natural_events` | disasters_server.py:43 | NASA EONET | All events incl. earthquakes (lower detail) |

All three return earthquake data. GDACS and NASA EONET also cover earthquakes alongside floods, cyclones, volcanoes, etc.

**Action**: Keep all three but clarify docstrings. USGS is the detailed earthquake tool; GDACS/EONET are multi-hazard alert tools. Consider a provider-agnostic wrapper (see Section 2).

---

## 2. Provider-Agnostic Routing Opportunities

These are cases where the LLM must currently know which tool to call for a given data concept, when a single "smart" tool could auto-route based on parameters.

### 2.1 Economic Indicators — HIGH VALUE

**Current state**: 5 tools across 3 providers for economic data:
- `econ_fred_series(series_id)` — US only, requires API key, highest frequency
- `econ_fred_search(query)` — search FRED catalog
- `econ_worldbank_indicator(indicator, country)` — 190+ countries, no key, annual
- `econ_worldbank_search(query)` — search WB catalog
- `econ_imf_data(database, ref_area, indicator)` — 190+ countries, no key, complex params

**Problem**: For "GDP of Germany" the LLM must decide between World Bank (`NY.GDP.MKTP.CD`) and IMF (`NGDP_R_XDC` in IFS). For "US unemployment" it must choose between FRED (`UNRATE`) and World Bank (`SL.UEM.TOTL.ZS`).

**Proposed**: Add a high-level routing tool:

```python
@mcp.tool()
async def indicator(concept: str, country: str = "", years: str = "") -> dict:
    """Economic indicator by concept. Auto-routes to best provider.
    concept: gdp, inflation, unemployment, interest_rate, trade_balance, population, etc.
    country: ISO2/ISO3 code. If US-only indicator, uses FRED. Otherwise World Bank."""
```

**Routing logic**:
| Concept | US → | Non-US → | Fallback → |
|---------|------|----------|------------|
| GDP | FRED (`GDP`) | World Bank (`NY.GDP.MKTP.CD`) | IMF IFS |
| CPI/Inflation | FRED (`CPIAUCSL`) | World Bank (`FP.CPI.TOTL.ZG`) | IMF IFS |
| Unemployment | FRED (`UNRATE`) | World Bank (`SL.UEM.TOTL.ZS`) | — |
| Interest Rate | FRED (`DFF`) | IMF IFS | — |
| Population | — | World Bank (`SP.POP.TOTL`) | — |

**Keep underlying tools** for power users who want specific series IDs. The router is an additional convenience layer.

### 2.2 Disaster / Natural Events — MEDIUM VALUE

**Current state**: 3 tools, 3 providers:
- `disaster_get_earthquakes` — USGS, earthquakes only, high detail
- `disaster_get_disasters` — GDACS, multi-hazard, alert-level
- `disaster_get_natural_events` — NASA EONET, multi-hazard, event-tracking

**Proposed**: Add a unified entry point:

```python
@mcp.tool()
async def hazard_alerts(hazard: str = "", days: int = 7,
                        min_severity: str = "") -> dict:
    """Natural hazard alerts. Auto-selects best source.
    hazard: earthquake, flood, cyclone, volcano, wildfire, drought, all.
    For earthquakes: routes to USGS (detailed). Others: GDACS + EONET."""
```

### 2.3 Conflict Events — LOWER VALUE

**Current state**: 2 tools:
- `conflict_ucdp_conflicts(year)` — UCDP, academic, annual, free
- `conflict_acled_events(country, event_type)` — ACLED, real-time, requires API key

**These are complementary** (UCDP is historical/academic, ACLED is real-time/operational). A router adds marginal value since use cases differ. Keep as-is.

---

## 3. Utility MCP Assessment

### Current Architecture (4 MCP server processes)

| Server | Transport | Package | Purpose |
|--------|-----------|---------|---------|
| **trading** | streamable-http :8071 | FastMCP (Python) | Store + 9 data domains |
| **filesystem** | stdio | `@modelcontextprotocol/server-filesystem` | File read/write in `~/TradeAssistant_Data/files/` |

### Overlap with Trading Store?

| Capability | Store Already Does | Utility MCP Adds |
|------------|-------------------|------------------|
| Document storage | Profiles (structured, MongoDB collections) | Arbitrary files (exports, reports, PDFs) |
| Knowledge persistence | Notes + memory (per-user, MongoDB) | N/A |
**Verdict**: **No functional overlap.** The store handles domain-specific structured data (profiles, snapshots, notes, memory). The filesystem MCP handles ad-hoc user data (files). Keep separate.

### Could We Drop Any?

| MCP | Drop? | Rationale |
|-----|-------|-----------|
| **filesystem** | No | Needed for user exports, report generation, document storage |

---

## 4. Tool Count Optimization Summary

### Before (current)

| Namespace | Tools | External APIs |
|-----------|-------|---------------|
| store | 24 | MongoDB |
| econ | 5 | FRED, World Bank, IMF |
| weather | 6 | Open-Meteo, NOAA, USGS, USDM |
| disaster | 3 | USGS, GDACS, NASA |
| conflict | 7 | UCDP, ACLED, OpenSanctions, World Bank, UNHCR, HDX, ReliefWeb |
| agri | 4 | FAOSTAT, USDA NASS |
| commodity | 2 | UN Comtrade, EIA |
| health | 4 | WHO, disease.sh, OpenFDA |
| politics | 7 | Wikidata, EU Parliament, Google Civic, ReliefWeb |
| transport | 5 | OpenSky, AIS, Cloudflare, RIPE |
| **Total** | **67** | **25+ APIs** |

### After (proposed)

| Change | Tools Removed | Tools Added | Net |
|--------|--------------|-------------|-----|
| Remove `election_reports` (ReliefWeb dupe) | -1 | — | -1 |
| Remove `military_spending` (WB wrapper) | -1 | — | -1 |
| Add `indicator()` router | — | +1 | +1 |
| Add `hazard_alerts()` router | — | +1 | +1 |
| **Net change** | **-2** | **+2** | **0** |

Tool count stays the same, but **LLM decision quality improves** — the routers handle provider selection that the LLM currently guesses at.

---

## 5. Recommended Actions

### Immediate (P0) — ✅ DONE

1. ~~**Remove `politics_election_reports`** from `elections_server.py`~~ — removed (was never implemented)
2. ~~**Remove `conflict_military_spending`** from `conflict_server.py`~~ — removed; `MS.MIL.XPND.GD.ZS` documented in `worldbank_indicator` docstring + available via `indicator(concept="military_spending")`

### Short-term (P1)

3. **Add `econ_indicator()` router** in `macro_server.py` — auto-routes GDP/CPI/unemployment to best provider by country
4. **Add `disaster_hazard_alerts()` router** in `disasters_server.py` — unified entry for multi-hazard queries

### Monitor (P2)

5. **Add docstring disambiguation** to disaster tools — make it clear when to use USGS vs GDACS vs EONET

---

## 6. Provider-Agnostic Design Pattern

For future tools, follow this pattern:

```python
# High-level router (provider-agnostic, LLM-friendly)
@mcp.tool()
async def indicator(concept: str, country: str = "", years: str = "") -> dict:
    """Economic indicator by concept. Auto-routes to best provider."""
    provider = _select_provider(concept, country)
    return await provider.fetch(concept, country, years)

# Low-level tools (provider-specific, power-user access)
@mcp.tool()
async def fred_series(series_id: str, ...) -> dict: ...
@mcp.tool()
async def worldbank_indicator(indicator: str, ...) -> dict: ...
```

**Principle**: Present **concepts** at the top level, **providers** underneath. The LLM asks for "GDP of Germany" → the tool figures out World Bank is the right source. Power users can still call `fred_series("GDP")` directly.

This pattern scales: as new providers are added (Eurostat, OECD, ECB), the router absorbs them without increasing tool count or LLM decision burden.

---

## 7. External MCP Servers — Cross-Reference vs. Existing Stack

Evaluated 35 curated external MCP servers against our 67 internal tools. Verdict for each: **SKIP** (we already cover it), **ADD** (genuinely new capability), or **WATCH** (nice-to-have, low priority).

### 7.1 Cloud MCPs

| # | Server | Overlap with Our Stack | Verdict |
|---|--------|----------------------|---------|
| 1 | **GDELT Cloud** (`gdelt-cloud-mcp.fastmcp.app`) | We have NO news/events/sentiment tool. GDELT adds 65-language news, entity sentiment, 150-country coverage, hourly. | **ADD** — Fills our biggest gap. No internal equivalent. |
| 2 | **Alpha Vantage** (`mcp.alphavantage.co`) | We have NO stock price/OHLCV tool. Our `econ_fred_series` has VIXCLS but no individual stocks. | **ADD** — Stock/forex/crypto prices + 50 TA indicators. 25 calls/day limit is tight though. |
| 3 | **dr-manhattan** (prediction markets) | We have NO prediction market tool. | **ADD** — 5 platforms unified. Unique signal source. |
| 4 | **Apify GDELT** | Redundant if we add #1 (GDELT Cloud). Apify adds scraping but we don't need it. | **SKIP** — #1 is better and direct. |

### 7.2 Self-Hosted — Zero Auth

| # | Server | Overlap with Our Stack | Verdict |
|---|--------|----------------------|---------|
| 5 | **prediction-market-mcp** (JamesANZ) | Same gap as #3. Polymarket + PredictIt + Kalshi, zero config. | **ADD** — Simpler than dr-manhattan, zero keys. One-liner install. |
| 6 | **yahoo-finance-mcp** | We have NO stock price tool. | **ADD** — OHLCV, financials, options, news. Zero auth. **Best stock data pick.** |
| 7 | **hn-mcp** (Hacker News) | We have NO tech news/sentiment tool. | **ADD** — Tech sentiment signal. Lightweight. |
| 8 | **arxiv-mcp-server** | We have NO research paper tool. | **WATCH** — Useful for deep research but not direct trading signal. |
| 9 | **mcp-server-reddit** | We have NO social sentiment tool. | **ADD** — Reddit sentiment = retail investor signal. |
| 10 | **rss-mcp** (veithly) | We have NO RSS tool. RSSHub routes cover LinkedIn, SEC filings, GitHub trending, PH, YC. | **ADD** — Sleeper pick. Massive coverage via RSSHub without API keys. SEC filings alone justify it. |
| 11 | **MCP-Mathematics** | Our stack does NO local computation (math, stats, financial calcs). | **WATCH** — NPV/IRR calcs useful but LLM can do basic math. |
| 12 | **mcp-ols** (regression) | We have NO statistical modeling. | **WATCH** — OLS + diagnostics. Useful once we have enough snapshot data for backtesting. |
| 13 | **crypto-feargreed-mcp** | We have NO crypto sentiment. | **ADD** — Lightweight, zero auth, real-time index. |
| 14 | **whale-tracker-mcp** | We have NO on-chain analytics. | **WATCH** — Niche. Only useful if actively trading crypto. |
| 15 | **patent_mcp_server** | We have NO IP/patent tool. | **WATCH** — Useful for company deep dives, not routine signals. |
| 16 | **polymarket-predictions-mcp** | Covered by #5 (prediction-market-mcp) which does 3 platforms. | **SKIP** — #5 is strictly better. |

### 7.3 Self-Hosted — Free Key

| # | Server | Overlap with Our Stack | Verdict |
|---|--------|----------------------|---------|
| 17 | **kylezarif/mcp** (geopolitical) | **HEAVY overlap**: SEC EDGAR (new), Treasury (new), BUT World Bank = our `econ_worldbank_indicator`, ECB = could route through our `econ_imf_data`, Stooq prices (new), FHFA housing (new), GDELT = #1. | **PARTIAL** — SEC EDGAR + Treasury + Stooq are new. World Bank/ECB are wasteful dupes. |
| 18 | **paper-search-mcp** | Superset of #8 (arXiv + PubMed + Scholar + more). | **WATCH** — Replaces #8 if research is needed. |
| 19 | **rss-news-analyzer** | Overlaps with #10 (rss-mcp) but adds trend spike detection. Requires OpenAI key. | **SKIP** — #10 is better (zero LLM key dependency). |
| 20 | **cryptopanic-mcp** | We have NO crypto news aggregation. | **WATCH** — Marginal over #13 (fear & greed) + #9 (reddit crypto subs). |
| 21 | **producthunt-mcp** | No overlap. | **WATCH** — Niche. Startup signal, not trading. |
| 22 | **twitter-mcp-server** | We have NO Twitter/X tool. | **ADD** — Social sentiment from X is a strong trading signal. Requires X API creds. |
| 23 | **mcp-wolfram-alpha** | We have NO symbolic math/science data. | **WATCH** — Wolfram's curated datasets are unique but 2k/mo limit. |
| 24 | **prediction-scorer** | We have NO forecast calibration. | **WATCH** — Useful once we have prediction history to score. |

### 7.4 Self-Hosted — Trading & Strategy

| # | Server | Overlap with Our Stack | Verdict |
|---|--------|----------------------|---------|
| 25 | **maverick-mcp** (TA + backtest) | We have NO technical analysis or backtesting. | **ADD** — 20+ TA indicators, 15+ strategies, screening, portfolio opt. Heavy (TA-Lib C dep) but comprehensive. |
| 26 | **QuantConnect** (official) | We have NO algo trading platform. | **WATCH** — Full algo trading lifecycle. Relevant once strategy execution is needed. |
| 27 | **quantconnect-mcp** (advanced) | Superset of #26 + PCA, cointegration, mean-reversion. | **WATCH** — Same as #26, more quant tools. Pick one. |
| 28 | **polymarket-mcp-server** (trade) | #5 covers read-only. This adds trading execution. | **WATCH** — Only needed for actual Polymarket trading. |
| 29 | **polymaster** (whale anomalies) | We have NO whale detection. | **WATCH** — Niche anomaly scoring. |
| 30 | **mcp-predictive-market** (arb) | Cross-market arbitrage detection across 5 platforms. | **WATCH** — Advanced. Interesting once prediction market strategy matures. |

### 7.5 Self-Hosted — OSINT

| # | Server | Overlap with Our Stack | Verdict |
|---|--------|----------------------|---------|
| 31 | **mcp-maigret** (username hunt) | No overlap. | **SKIP** — Not trading-relevant. |
| 32 | **mcp-shodan** (network intel) | Our `transport_internet_traffic` (Cloudflare Radar) + `transport_ripe_probes` cover some infra monitoring. Shodan adds device/CVE. | **WATCH** — Different angle (security vs traffic). |
| 33 | **mcp-dnstwist** (typosquatting) | No overlap. | **SKIP** — Security-focused, not trading. |
| 34 | **mcp-virustotal** (malware) | No overlap. | **SKIP** — Security-focused, not trading. |
| 35 | **pentest-osint-mcp** | No overlap. | **SKIP** — Security toolkit. |

---

## 8. Wasteful Cloud MCPs — What to Curate/Wrap

These external MCPs **duplicate what our stack already does** and should NOT be added as separate MCP connections:

| External MCP | Our Equivalent | Why It's Wasteful |
|--------------|---------------|-------------------|
| **kylezarif/mcp** World Bank tools | `econ_worldbank_indicator` | Same API, same data. Adding a second MCP that calls World Bank = double tool surface for LLM to navigate. |
| **kylezarif/mcp** ECB tools | `econ_imf_data` (covers ECB via SDMX) | ECB publishes via SDMX, which IMF aggregates. |
| **Apify GDELT** (#4) | GDELT Cloud (#1) | Apify wraps GDELT with extra scraping layer and account requirement. GDELT Cloud is direct. |
| **rss-news-analyzer** (#19) | **rss-mcp** (#10) | Adds OpenAI key dependency for trend detection. RSS feed reading is the core value; trend detection belongs in our analysis layer. |
| **polymarket-predictions-mcp** (#16) | **prediction-market-mcp** (#5) | Single-platform subset of #5's 3-platform coverage. |
| **Alpha Vantage** (#2) | **yahoo-finance-mcp** (#6) | Alpha Vantage has 25/day limit. Yahoo Finance has zero auth and broader coverage. AV only wins on TA indicators (but #25 maverick covers that). |

### Curate Strategy for kylezarif/mcp (#17)

This is the most interesting case — 7 data sources in 1 MCP, but only 3 are new to us:

| Source | Already Have? | Action |
|--------|--------------|--------|
| GDELT news | No → add via #1 (cloud) | Use GDELT Cloud directly |
| SEC EDGAR | **No** | **Cherry-pick** — add SEC filing tool to our stack |
| US Treasury | **No** | **Cherry-pick** — add Treasury yield/auction tool |
| Stooq prices | **No** | Superseded by yahoo-finance-mcp (#6) |
| World Bank | Yes (`econ_worldbank_indicator`) | **Skip** — wasteful duplicate |
| ECB | Yes (via `econ_imf_data`) | **Skip** — wasteful duplicate |
| FHFA housing | **No** | **Cherry-pick** — niche but useful for real estate exposure |

**Recommendation**: Don't add kylezarif/mcp as-is. Instead, cherry-pick SEC EDGAR and Treasury tools into our `macro_server.py` or a new `us_gov_server.py`.

---

## 9. Recommended External MCP Stack

### Tier 1 — Add Now (fills clear gaps, zero/low friction)

| Priority | Server | Category | Why | Install |
|----------|--------|----------|-----|---------|
| **1** | **yahoo-finance-mcp** (#6) | Stocks/prices | Zero auth OHLCV + financials. Our biggest data gap. | `pip install` |
| **2** | **GDELT Cloud** (#1) | News/events | 65-language news sentiment. No install needed. | Cloud endpoint |
| **3** | **prediction-market-mcp** (#5) | Predictions | 3 platforms, zero config. Unique signal. | `npx` one-liner |
| **4** | **rss-mcp** (#10) | RSS/feeds | SEC filings, LinkedIn, GitHub trending via RSSHub. | `npm install` |
| **5** | **mcp-server-reddit** (#9) | Social | Retail investor sentiment. | `uvx` one-liner |

### Tier 2 — Add When Needed (useful but not urgent)

| Server | Category | When |
|--------|----------|------|
| **twitter-mcp-server** (#22) | Social/X | When X API creds available |
| **maverick-mcp** (#25) | TA/backtest | When building strategy backtesting |
| **hn-mcp** (#7) | Tech news | When monitoring tech sector specifically |
| **crypto-feargreed-mcp** (#13) | Crypto sentiment | When actively trading crypto |

### Tier 3 — Watch (interesting, premature now)

arxiv (#8), mcp-ols (#12), wolfram (#23), quantconnect (#26/#27), prediction-scorer (#24), whale-tracker (#14)

### Skip (wasteful or off-topic)

#4 (Apify GDELT), #16 (single-platform polymarket), #19 (RSS+OpenAI dep), #31/#33/#34/#35 (security OSINT)

---

## 10. Auto-Routing Architecture for External MCPs

External MCPs should plug into the same provider-agnostic pattern. When yahoo-finance-mcp is added, it becomes another provider behind our routing layer:

```
User asks: "AAPL stock price"
                    │
        ┌───────────▼────────────┐
        │   provider-agnostic    │
        │   routing layer        │
        │                        │
        │  concept: stock_price  │
        │  entity: AAPL          │
        └───────┬────────────────┘
                │
    ┌───────────┼──────────────┐
    ▼           ▼              ▼
yahoo-finance  Alpha Vantage  (future: IEX, Polygon)
(preferred:    (fallback:     (fallback:
 zero auth)    25/day limit)   paid tier)
```

### Implementation: Don't Mount External MCPs Directly

Instead of mounting yahoo-finance-mcp as a separate MCP connection in librechat.yaml (which adds tool surface area for the LLM), **wrap it inside our trading server**:

```python
# In a new src/servers/market_server.py
@mcp.tool()
async def stock_price(symbol: str, period: str = "1mo") -> dict:
    """Stock price history. Auto-selects provider."""
    # Calls yahoo-finance-mcp's internal functions
    # or directly calls yfinance API
    ...

@mcp.tool()
async def stock_fundamentals(symbol: str) -> dict:
    """Company fundamentals (PE, EPS, revenue, margins)."""
    ...
```

This keeps the LLM's tool surface **flat and curated** instead of exploding with N external MCPs each exposing their own tool names.

### The Wrapping Principle

| Approach | Tools Visible to LLM | LLM Decision Burden |
|----------|---------------------|-------------------|
| Mount 5 external MCPs directly | 67 + ~40 external = **107 tools** | High — LLM must pick between `yahoo_get_stock_price`, `alphavantage_stock_data`, `maverick_stock_screen` |
| Wrap behind our routing layer | 67 + ~8 routers = **75 tools** | Low — LLM calls `stock_price("AAPL")`, router picks provider |

**Rule**: Every external MCP should be evaluated as "do we wrap it or mount it directly?" Default to wrapping unless the external MCP provides a genuinely distinct *category* of capability (like prediction markets).
