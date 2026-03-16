# TODO — MCP Signals Stack

Global roadmap and task list. Updated 2026-03-16 (fresh state audit).

---

## P0 — Foundation (do first)

- [x] **Validate combined trading server runs without errors**
      Combined server (store + 12 domains) mounts all namespaces.
      CI smoke test verifies 75+ tools, all 15 namespaces mounted.
- [x] **Test signals store against live Atlas M0**
      `snapshot()`, `event()`, `history()`, `trend()`, `aggregate()`, `nearby()` round-trip verified.
      Fixed: sparse indexes on timeseries, invalid `"days"` granularity.
      Integration tests in CI (test_integration_store.py, test_smoke_combined.py).
- [x] **Populate seed country profiles**
      162 country profiles across 10 regions (Europe 44, Sub-Saharan Africa 37,
      Latin America 21, MENA 19, Southeast Asia 11, South Asia 8, East Asia 8,
      Oceania 6, Central Asia 5, North America 3). (2026-03-16)
- [x] **Populate seed entity profiles**
      63 stocks across 8 regions, 30 ETFs, 10 crypto, 15 indices,
      15 commodities, 15 materials, 15 crops, 15 companies, 10 products,
      51 regions. Total: 424 profile files. (2026-03-16)
- [ ] **Add more source profiles** for the 75+ data sources
      Currently 23 sources (WHO, IMF, FAO, NASA, etc.). Each FastMCP server maps to
      multiple sources — create profiles for at least the top 2 per domain.
- [x] **Placeholder profiles by design**
      All 424 seed profiles are marked `_placeholder: true` — this is intentional.
      Seed data provides structure; live MCP data enriches on first use.

---

## P1 — Integration & Data Pipeline

- [x] **Build periodic ingest scheduler (cron-planner agent)**
      Cron-planner agent invoked every 6 hours via `ta cron` using LibreChat Agents API.
      Agent reads plans/watchlists, delegates to L1 data agents, triggers L2 analysis.
- [x] **Wire price ingestion for indicator computation**
      Decoupled `src/ingest/price_ingest.py`: fetches OHLCV from Yahoo Finance,
      computes indicators via ta server, stores both as snapshots (price + indicators).
      Emits signal_change events when composite signal changes.
      CLI: `augur ingest [kinds]`. Cron: every 6 hours at :05–:14.
- [ ] **Add Volume-Weighted Average Price (VWAP) indicator**
      Requires volume data. Price ingestion already fetches OHLCV with volume.
- [ ] **Add ATR (Average True Range) indicator**
      Requires high/low/close (available from Yahoo OHLCV). Useful for position sizing
      and stop-loss placement.
- [x] **Build periodic ingest scheduler**
      Price ingestion runs every 6 hours via `augur cron` (Augur.sh).
      Iterates all profiled stocks/etfs/crypto/indices, fetches OHLCV,
      stores snapshots, emits events on signal changes.
      Future: extend to macro indicators for countries, commodity prices.
- [ ] **Wire up profile ↔ snapshot cross-references**
      When a snapshot is stored for entity "AAPL", auto-link to the profile's risk factors,
      supply chain deps, and country exposures.
- [x] **Add event-to-profile impact mapping**
      `src/alerts/impact_mapper.py`: post-event hook in store `event()` for
      high/critical severity. Queries profiles with `exposure.countries` match,
      creates impact snapshots cross-referencing the event.
- [x] **Implement alert/threshold system**
      `src/alerts/threshold_checker.py`: pure-function threshold evaluator.
      Supports ops: <, >, <=, >=, ==, !=, absent. Dot-notation nested fields.
      Hooked into store `snapshot()`: checks entity profile thresholds after
      each snapshot, emits threshold_breach events on match.

---

## P2 — Server Improvements

- [ ] **Optimize `find_profile()` for scale** (REVIEW.md #52)
      Cross-kind search does 36 MongoDB queries per call (3 × 12 kinds).
      Fine at current scale (424 profiles). At 1000+, consider a unified search
      collection or MongoDB Atlas Search.
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
- [ ] **Fix `OAuthToken.headers()` KeyError** (REVIEW.md #46)
      Missing `access_token` in OAuth response raises uncaught `KeyError`.
- [ ] **Fix `_replace_field()` regex injection** (REVIEW.md #47)
      Backslash sequences in `outcome_note` corrupt YAML front matter.
- [ ] **Fix `price_ingest.py` close field None check** (REVIEW.md #49)
      `close` field missing None guard — crashes on null Yahoo Finance data.
- [ ] **Fix signal change detection order** (REVIEW.md #50)
      Fetch old composite signal before storing new snapshot, not after.
- [ ] **Add async support to signals store**
      `server.py` uses sync `pymongo`. Consider `motor` for async MongoDB if needed
      for concurrent snapshot ingestion.
- [ ] **Add rate limiting awareness to source servers**
      Some APIs (ACLED, Google Civic, AIS Stream) have rate limits. Track and respect them.
- [ ] **Add health check tool to each server**
      `health()` tool that returns status, last successful call time, and API availability.

---

## P3 — Profile Expansion

- [x] **Generate country profiles**
      162 country profiles from World Bank / CIA Factbook data across 10 regions.
      (2026-03-16)
- [ ] **Enrich entity profiles from SEC EDGAR / Yahoo Finance**
      63 stock profiles exist as seed data. Enrich with real fundamentals
      (debt/assets, P/E, sector exposure, revenue) from SEC EDGAR / Yahoo Finance.
- [x] **Add crypto profiles** (BTC, ETH, SOL, and top-10)
      10 crypto profiles in `profiles/global/crypto/`. (2026-03-16)
- [x] **Add index profiles** (SPX, NDX, DJI, FTSE, DAX, N225, etc.)
      15 index profiles in `profiles/global/indices/`. (2026-03-16)
- [x] **Add ETF profiles** for key sector/country/commodity exposure
      30 ETF profiles in `profiles/global/etfs/` (SPY, QQQ, EEM, GLD, etc.). (2026-03-16)
- [x] **Add commodity, material, crop, company, product profiles**
      15 commodities, 15 materials, 15 crops, 15 companies, 10 products,
      51 region profiles. All in `profiles/global/`. (2026-03-16)

---

## P4 — Deployment & Ops

- [x] **Set up CI/CD** (GitHub Actions)
      87+ unit tests (bats + pytest), integration tests against Atlas, E2E smoke tests,
      ShellCheck on all scripts. Release workflow builds bundle on tag push.
- [x] **Automate LibreChat setup**
      `augur install` auto-derives MONGO_URI_SIGNALS, auto-seeds agents (if credentials set),
      auto-sets up data repo (if SSH key exists), rebuilds profile indexes.
      `remoteAgents` enabled by default in librechat.yaml.
- [x] **MongoDB Atlas backup to Uberspace disk (rolling)**
      `augur backup` / `augur restore` / `augur backups` — pymongo-based gzipped JSON dumps
      to `~/backups/mongo/` with rolling retention: daily (7), weekly (4), monthly (3).
      Runs automatically via `augur cron` at 02:00 UTC alongside compact job.
      No git — dumps don't diff well. ~10-50 MB compressed per dump.
- [x] **Uberspace deployment** (nearly complete)
      Systemd services (librechat, augur, charts), cron scheduling, .env pickup,
      log rotation, first-login user setup (`augur user`). MCP timeout increased
      to 300s. LibreChat connectivity fixed (0.0.0.0 binding, health endpoint).
      Remaining: final end-to-end verification pass on live host.
- [ ] **Final deployment verification**
      Run full `augur install` on live Uberspace host. Verify all services start,
      Atlas connects, MCP servers respond, profile seeding works, cron runs.
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
- [x] **Price ingestion pipeline** — decoupled `src/ingest/price_ingest.py` bridges
      ta server (Yahoo OHLCV + indicators) and store (snapshots). Cron-scheduled
      every 6 hours. CLI: `augur ingest`. 16 tests. (2026-03-12)
- [x] **Threshold checker** — `src/alerts/threshold_checker.py`: pure-function
      evaluator for profile `signal.thresholds`. Ops: <, >, <=, >=, ==, !=, absent.
      Auto-hooked into store `snapshot()`. 22 tests. (2026-03-12)
- [x] **Event-to-profile impact mapper** — `src/alerts/impact_mapper.py`: post-event
      hook for high/critical events. Queries `exposure.countries` across 8 profile
      kinds, creates impact snapshots. 14 tests. (2026-03-12)
- [x] **Seed profiles (424 files)** — 162 countries, 63 stocks, 30 ETFs, 10 crypto,
      15 indices, 15 commodities, 15 materials, 15 crops, 15 companies, 10 products,
      51 regions, 23 sources. Organized by region. All `_placeholder: true` (seed data,
      enriched by live MCP). (2026-03-16)
- [x] **Third code review** — fresh security/quality audit (REVIEW.md). 5 new warnings
      found (#46-50), 1 accepted (#51), 1 low/style (#52). No new critical issues.
      (2026-03-16)
