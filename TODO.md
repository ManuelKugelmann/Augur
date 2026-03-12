# TODO — MCP Signals Stack

Global roadmap and task list. Updated 2026-03-09 (staging readiness pass).

---

## P0 — Foundation (do first)

- [x] **Validate combined trading server runs without errors**
      Combined server (store + 12 domains) mounts all namespaces.
      CI smoke test verifies 50+ tools, all 13 namespaces mounted.
- [x] **Test signals store against live Atlas M0**
      `snapshot()`, `event()`, `history()`, `trend()`, `aggregate()`, `nearby()` round-trip verified.
      Fixed: sparse indexes on timeseries, invalid `"days"` granularity.
      Integration tests in CI (test_integration_store.py, test_smoke_combined.py).
- [ ] **Populate seed country profiles** (~20 major economies)
      Currently only DEU and USA. Need at minimum: CHN, JPN, GBR, FRA, IND, BRA, KOR,
      AUS, CAN, RUS, SAU, ZAF, MEX, IDN, TUR, ITA, ESP, NLD, CHE, SGP.
- [ ] **Populate seed entity profiles** (~20 stocks, ~5 ETFs)
      Currently only AAPL, NVDA, VWO. Need major index constituents and key ETFs
      (SPY, QQQ, EEM, GLD, USO, etc.).
- [ ] **Add more source profiles** for the 75+ data sources
      Currently only 3 (usgs, faostat, open-meteo). Each FastMCP server maps to
      multiple sources — create profiles for at least the top 2 per domain.
- [ ] **Generate INDEX files** (`profiles/INDEX_*.json`)
      Currently missing on disk. `rebuild_index()` exists but hasn't been run.
      Install script calls it at step 13 — verify it works with current profiles.
- [ ] **Fix placeholder profiles** (USA.json, faostat.json)
      Both have `_placeholder: true` with incomplete data. Fill in real values.

---

## P1 — Integration & Data Pipeline

- [x] **Build periodic ingest scheduler (cron-planner agent)**
      Cron-planner agent invoked every 6 hours via `ta cron` using LibreChat Agents API.
      Agent reads plans/watchlists, delegates to L1 data agents, triggers L2 analysis.
- [ ] **Wire price ingestion for indicator computation**
      Indicators server (`ta_*` namespace) is pure math — needs OHLCV input.
      Options: (a) yahoo-finance MCP → snapshot → feed to indicators, or
      (b) direct tool chaining in LLM context. Start with (b), add (a) in scheduler.
- [ ] **Add Volume-Weighted Average Price (VWAP) indicator**
      Requires volume data. Add once price ingestion is in place.
- [ ] **Add ATR (Average True Range) indicator**
      Requires high/low/close. Useful for position sizing and stop-loss placement.
- [ ] **Build periodic ingest scheduler**
      Cron or lightweight scheduler that calls domain MCP servers → stores snapshots.
      E.g., weekly: fetch prices for all entity profiles; monthly: fetch macro indicators
      for all country profiles; continuous: poll disaster/event feeds.
- [ ] **Wire up profile ↔ snapshot cross-references**
      When a snapshot is stored for entity "AAPL", auto-link to the profile's risk factors,
      supply chain deps, and country exposures.
- [ ] **Add event-to-profile impact mapping**
      When an earthquake event hits country "JPN", auto-tag entities with `exposure.countries`
      containing "JPN".
- [ ] **Implement alert/threshold system**
      Source profiles have `signal.thresholds` — build logic that checks incoming events
      against thresholds and flags high-severity signals.

---

## P2 — Server Improvements

- [ ] **Optimize `search_profiles()` for scale** (REVIEW.md #17)
      O(n) disk reads per query — reads every profile file. Fine for <100 profiles,
      will degrade at 500+. Options: in-memory cache with TTL, extend INDEX files
      with searchable fields, or MongoDB text search.
- [ ] **Add `econ_indicator()` routing improvements** (review-mcp-tools.md §2.1)
      Router exists in `macro_server.py`. Extend with ECB, OECD, Eurostat providers
      as they're added.
- [ ] **Add cross-reference validation to profile linter**
      `lint_profiles()` currently does basic checks (required fields, types).
      Add a `deep=True` mode that validates cross-references: country ISO3 codes
      in `exposure.countries` exist as profiles, `trade.top_partners` resolve,
      source `mcp` fields match actual server names, supply chain entity IDs exist.
- [x] **Add error handling to domain servers**
      All 12 servers now wrap HTTP calls in `try/except httpx.HTTPError` returning
      `{"error": ...}` instead of crashing. (2026-03-09)
- [ ] **Add async support to signals store**
      `server.py` uses sync `pymongo`. Consider `motor` for async MongoDB if needed
      for concurrent snapshot ingestion.
- [ ] **Add rate limiting awareness to source servers**
      Some APIs (ACLED, Google Civic, AIS Stream) have rate limits. Track and respect them.
- [ ] **Add health check tool to each server**
      `health()` tool that returns status, last successful call time, and API availability.

---

## P3 — Profile Expansion

- [ ] **Generate 200 country profiles from World Bank / CIA Factbook data**
      Script to fetch and populate `profiles/countries/` from free APIs.
- [ ] **Generate entity profiles from SEC EDGAR / Yahoo Finance**
      Script to fetch top stocks by market cap and populate `profiles/entities/stocks/`.
- [ ] **Add crypto profiles** (BTC, ETH, SOL, and top-20 by market cap)
      `profiles/entities/crypto/` — currently empty.
- [ ] **Add index profiles** (SPX, NDX, DJI, FTSE, DAX, N225, etc.)
      `profiles/entities/indices/` — currently empty.
- [ ] **Add ETF profiles** for key sector/country/commodity exposure
      VWO is the only one. Need SPY, QQQ, EEM, GLD, XLE, XLF, etc.

---

## P4 — Deployment & Ops

- [x] **Set up CI/CD** (GitHub Actions)
      87+ unit tests (bats + pytest), integration tests against Atlas, E2E smoke tests,
      ShellCheck on all scripts. Release workflow builds bundle on tag push.
- [x] **Automate LibreChat setup**
      `ta install` auto-derives MONGO_URI_SIGNALS, auto-seeds agents (if credentials set),
      auto-sets up data repo (if SSH key exists), rebuilds profile indexes.
      `remoteAgents` enabled by default in librechat.yaml.
- [x] **MongoDB Atlas backup to Uberspace disk (rolling)**
      `ta backup` / `ta restore` / `ta backups` — pymongo-based gzipped JSON dumps
      to `~/backups/mongo/` with rolling retention: daily (7), weekly (4), monthly (3).
      Runs automatically via `ta cron` at 02:00 UTC alongside compact job.
      No git — dumps don't diff well. ~10-50 MB compressed per dump.
- [ ] **Test Uberspace deployment end-to-end**
      Run `ta install` on a live Uberspace host.
      Verify systemd services start, logs rotate, .env is picked up.
- [ ] **Test LibreChat deployment end-to-end**
      Run the `augur-uberspace/` deployment package. Verify LibreChat connects
      to Atlas, MCP servers respond, git-versioned data sync works.
- [ ] **Add monitoring / health dashboard**
      Simple status page or script that checks: Atlas connection, each MCP server,
      last successful ingest timestamp per source.

---

## P5 — Documentation & Polish

- [ ] **Add CONTRIBUTING.md** with profile contribution guidelines
      How to add a new country/entity/source profile, naming conventions, schema rules.
- [ ] **Iterate on profile schemas based on actual MCP data**
      Run each domain server, inspect the data it returns, and update `_schema.json`
      files so profile fields match the real structure of MCP responses.
      Add fields that capture what the APIs actually provide; remove speculative ones.
- [ ] **Add JSON Schema validation** (proper `$schema` with `jsonschema` library)
      Current `_schema.json` files are descriptive, not machine-validatable.
      Convert to proper JSON Schema draft-07 or later.
- [ ] **Document MCP client integration** (how to connect from Claude/LibreChat)
      Add a `docs/mcp-client-setup.md` showing how to configure MCP clients
      to talk to the signals store and domain servers.
- [ ] **Consolidate overlapping docs**
      `trading-mcp-inventory.md` and `trading-stack-full.md` overlap significantly.
      Consider merging or clearly delineating scope.

---

## Completed

- [x] **Technical indicators server** — pure-math computation layer (SMA, EMA, RSI,
      Bollinger Bands, MACD, composite trend filter). Mounted as `ta_*` namespace.
      Based on NexusTrade 114K-backtest study: 200-day SMA trend filter (Layer 2) +
      RSI/Bollinger/MACD entry/exit timing (Layer 3). 34 tests. (2026-03-09)
- [x] **Repo init** — initial structure, 12 domain servers, signals store, profiles
- [x] **Repo cleanup** — add .gitignore, .env.example, fix nested dirs, align filenames,
      fix scripts, create TODO.md (2026-03-03)
- [x] **LibreChat full integration** — wire 12 trading MCPs + signals store into
      librechat.yaml, add __HOME__ path placeholders, add .env.example for LC,
      add GitHub Actions release workflow, update setup.sh for Python MCP deps,
      rewrite README with QuickStart (2026-03-03)
- [x] **Code review fixes** — all 5 critical security issues fixed (path traversal,
      aggregate pipeline, mutable defaults, shell injection, operator precedence),
      plus env var mismatches, datetime deprecation, Comtrade validation (2026-03-06)
- [x] **Test suite** — 87+ tests: 45 bats + 42+ pytest, CI on push/PR (2026-03-06)
- [x] **Multi-agent architecture** — 11 agents (L1-L5 + utility), seed script,
      handoff edges, web research tools on all tiers (2026-03-09)
- [x] **Web research MCPs** — fetch, webresearch, google-news, tavily added as
      Tier 1.5 MCPs with all agents having access (2026-03-09)
- [x] **Knowledge building** — all agents instructed to create/read notes for
      persistent memory, relationship discovery, and data source tracking (2026-03-09)
- [x] **MongoDB timeseries fixes** — sparse index removed from timeseries collections,
      invalid "days" granularity changed to "hours" (2026-03-09)
- [x] **E2E smoke tests** — LibreChat + trading server health, MCP tools, agents,
      MongoDB connectivity, cron API calls (2026-03-09)
- [x] **Provider-agnostic routing** — `econ_indicator()` router in macro_server.py
      auto-routes GDP/CPI/unemployment to FRED/World Bank/IMF by country.
      Duplicate tools (`election_reports`, `military_spending`) removed. (2026-03-09)
- [x] **HTTP timeouts on all servers** — explicit `timeout=` on every httpx call
      across all 12 domain servers + store. (2026-03-09)
- [x] **Error handling on all servers** — try/except httpx.HTTPError on all HTTP
      tools. Returns `{"error": ...}` instead of crashing. (2026-03-09)
