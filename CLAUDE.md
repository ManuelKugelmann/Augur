# CLAUDE.md — Project context for Claude Code

## Rules

- **Never circumvent or exclude failing tests.** Always find and fix the root cause. If not possible, discuss the problem with the user before proceeding.
- **Run tests locally before pushing.** Always run `python -m pytest tests/ -v` (and `bats tests/*.bats` if shell scripts changed) before committing and pushing. Do not push code that fails tests.
- **Prefer battle-tested libraries over custom code.** Use well-established libraries (e.g. `mongomock` for MongoDB mocks) instead of writing custom implementations — but don't explode the dependency tree for marginal gains.

## Project

**Augur** — An MCP-based trading signals platform deployed via LibreChat on Uberspace. 12 MCP servers: 1 combined trading server (signals store + 12 data domains + technical indicators, 50+ tools, 75+ data sources) via streamable-http + 5 Tier 1 external MCPs (finance, gdelt-cloud, prediction-markets, rss, reddit) + 6 Tier 2 external MCPs (alphavantage, hackernews, arxiv, math, regression, crypto-sentiment). Single process for trading server, multi-user: OSINT data is shared, notes/plans are per-user, trading keys are per-user via `customUserVars`. A risk gate guards all external trading actions.

## Naming Conventions

- **Repo**: `ManuelKugelmann/Augur`
- **Ops tool**: `Augur.sh` — single entry point for install + daily ops
  - `~/bin/augur` — primary shorthand (`augur help`, `augur status`, `augur install`, etc.)
  - `~/bin/Augur` — symlink to `augur`
  - Also works as one-liner: `curl ... Augur.sh | bash` (auto-detects fresh install)
- **Uberspace host**: `augur.uber.space`
- **Platform**: U8 (Arch Linux / systemd). U7 (CentOS 7 / supervisord) support is dormant — code paths remain but are not actively maintained. U7 has glibc 2.17 which blocks modern native modules (e.g. `sharp`).

## Directory Layout (Uberspace)

| Path | Purpose |
|------|---------|
| `~/augur/` | Clone of this repo (signals stack) |
| `~/LibreChat/` | LibreChat installation (from CI release bundle) |
| `~/backups/mongo/` | Rolling MongoDB backups (daily/weekly/monthly gzipped JSON) |
| `~/bin/augur` | Ops CLI tool |

## Directory Layout (Repo)

```
Augur/
├── CLAUDE.md                          ← you are here
├── README.md                          ← project overview
├── TODO.md                            ← roadmap (P0–P5)
├── deploy.conf                        ← central config, sourced by all scripts
├── requirements.txt                   ← Python deps: fastmcp, httpx, pymongo, python-dotenv, pandas, ta
├── .env.example                       ← signals stack env vars template
│
├── src/
│   ├── store/
│   │   └── server.py                  ← signals store (FastMCP, profiles + MongoDB snapshots)
│   └── servers/
│       ├── indicators_server.py       ← SMA, EMA, RSI, MACD, Bollinger + Yahoo-integrated analyze_* tools
│       ├── agri_server.py             ← FAOSTAT, USDA NASS/FAS, GIEWS, WASDE
│       ├── commodities_server.py      ← UN Comtrade, EIA, LME metals
│       ├── conflict_server.py         ← UCDP, ACLED, OpenSanctions, SIPRI
│       ├── disasters_server.py        ← USGS, GDACS, NASA EONET/FIRMS, EM-DAT
│       ├── elections_server.py        ← IFES, V-Dem, Google Civic, ReliefWeb
│       ├── health_server.py           ← WHO GHO, disease.sh, OpenFDA, ProMED
│       ├── humanitarian_server.py     ← UNHCR, OCHA HDX, ReliefWeb, IDMC
│       ├── infra_server.py            ← Cloudflare Radar, RIPE Atlas, IODA
│       ├── macro_server.py            ← FRED, World Bank, IMF, ECB, OECD, Eurostat
│       ├── transport_server.py        ← OpenSky Network, AIS Stream
│       ├── water_server.py            ← USGS Water, US Drought Monitor, GloFAS
│       └── weather_server.py          ← Open-Meteo, NOAA SWPC
│
├── profiles/                            ← seed data for install (JSON → MongoDB)
│   ├── INFO.md                        ← structure reference
│   ├── europe/, north_america/, ...   ← {region}/{kind}/{id}.json
│   └── global/                        ← non-geographic kinds (etfs, commodities, etc.)
│
├── librechat-uberspace/
│   ├── README.md                      ← deployment docs with QuickStart
│   ├── config/
│   │   ├── librechat.yaml             ← MCP server definitions (__HOME__ placeholders)
│   │   └── .env.example               ← LibreChat env template
│   └── scripts/
│       ├── Augur.sh                   ← ops CLI (installed as ~/bin/augur)
│       ├── bootstrap.sh               ← release download entry point
│       ├── setup.sh                   ← install/update with atomic swap
│       └── claude-auth-daemon.sh       ← Claude Max auth daemon
│
├── tests/
│   ├── conftest.py                    ← pytest conftest (mocks pymongo/fastmcp)
│   ├── helpers/
│   │   └── setup.bash                 ← shared bats helpers (sandbox, stubs)
│   ├── test_bootstrap.bats            ← syntax validation for all scripts
│   ├── test_deploy_conf.bats          ← config loading, env overrides
│   ├── test_install_lifecycle.bats    ← install → pull → update integration
│   ├── test_setup.bats                ← install/update modes, .env generation
│   ├── test_store.py                  ← pytest: profile CRUD, index, lint, search
│   ├── test_ta_cron.bats              ← cron hook (compact scheduling)
│   └── test_ta_dispatch.bats          ← help, status, version, restart, rollback
│
├── scripts/
│   └── mongo-backup.py                ← rolling MongoDB backup/restore (pymongo + gzip)
│
├── docs/
│   ├── librechat-uberspace-setup.md   ← step-by-step deployment guide
│   ├── architecture-signals-store.md  ← store architecture
│   ├── global-datasources-75.md       ← data source inventory
│   ├── trading-mcp-inventory.md       ← MCP server inventory
│   ├── trading-stack-full.md          ← full stack description
│   └── uberspace-deployment.md        ← deployment notes
│
└── .github/workflows/
    ├── release.yml                    ← CI: tag push → build bundle → GitHub Release
    └── tests.yml                      ← CI: bats tests + ShellCheck on push/PR
```

## Architecture

```
Dev (Claude Code / Codespace)
  │ push / tag
  ▼
GitHub (Augur) ──tag──▶ CI builds bundle ──▶ GitHub Release
                                                             │
                                  ┌──────────────────────────┘
                                  ▼
                           Uberspace (augur.uber.space)
                           ├─ LibreChat (:3080, Node.js)
                           │   ├─ MCP: trading ──streamable-http──▶ :8071/mcp
                           │   ├─ MCP: Tier 1 external (finance, gdelt-cloud,
                           │   │       prediction-markets, rss, reddit)
                           │   ├─ MCP: Tier 2 external (alphavantage, hackernews,
                           │   │       arxiv, math, regression, crypto-sentiment)
                           │         X-User-ID / X-User-Email injected per request
                           │         customUserVars: BROKER_API_KEY, BROKER_API_SECRET
                           │
                           ├─ trading server (:8071, Python, store + 12 domains, 50+ tools)
                           │   ├─ shared: OSINT data, profiles, snapshots, events
                           │   ├─ per-user: notes/plans (MongoDB user_notes), risk gate
                           │   └─ per-user: broker keys (headers, never stored)
                           │
                           └─ cron (daily at 02:00 UTC)
                                  │
                            ┌─────┼──────┐
                            ▼     ▼      ▼
                       MongoDB  Cloud   75+ free
                       Atlas    LLMs    data APIs
```

## Key Technical Details

### Combined Trading Server (`src/servers/combined_server.py`)
- **Architecture**: Signals store + 12 data domains + technical indicators combined via FastMCP `mount(namespace=)`
- **Transport**: streamable-http on `:8071/mcp` (`stateless_http=True`), falls back to stdio for dev/testing
- **Entry point**: `combined_server.py` mounts `store/server.py` as `store` namespace + 12 domain servers
- **Tool namespacing**: `store_get_profile`, `weather_forecast`, `econ_fred_series`, `ta_analyze_full`, etc.
- **Multi-user**: LibreChat injects `X-User-ID` / `X-User-Email` headers per request; `_get_user_id()` reads them via `fastmcp.server.dependencies.get_http_headers()`
- **Per-user isolation**: notes/plans scoped by `user_id` in MongoDB; broker keys passed as headers (never stored); snapshots/events tagged with `user_id` in meta
- **Risk gate**: `_risk_check()` enforces user identification, dry_run default, daily action limits before any external trading API call
- **Per-user keys**: `customUserVars` in `librechat.yaml` lets each user set `BROKER_API_KEY` / `BROKER_API_SECRET`; forwarded as HTTP headers, read via `_get_user_key()`
- Individual servers (`store/server.py`, `weather_server.py`, etc.) still work standalone for testing

#### Signals Store (store_* namespace)
- **Profiles** (shared): MongoDB collections `profiles_{kind}` (one per kind), text + geo indexes
- **Snapshots** (shared): Per-kind timeseries collections (`snap_{kind}`, `arch_{kind}`, `events`); snapshots/events include `user_id` in meta
- **Notes** (per-user): `user_notes` collection keyed by `user_id` — plans, watchlists, journal entries
- **Risk gate** (per-user): `risk_status()` tool, `_risk_check()` guard for trading actions, configurable daily limit
- **Geo support**: Optional GeoJSON `location` field, 2dsphere indexes, `nearby()` tool
- **Profile tools**: `store_get_profile`, `store_put_profile`, `store_list_profiles`, `store_find_profile`, `store_search_profiles`, `store_list_regions`, `store_lint_profiles`
- **Snapshot tools**: `store_snapshot`, `store_history`, `store_trend`, `store_nearby`, `store_event`, `store_recent_events`, `store_archive_snapshot`, `store_archive_history`, `store_compact`, `store_aggregate`, `store_chart`
- **Notes tools** (per-user): `store_save_note`, `store_get_notes`, `store_update_note`, `store_delete_note`
- **Research tools** (shared): `store_save_research`, `store_get_research`, `store_update_research`, `store_delete_research`
- **Notification tool**: `store_notify` (per-user push via ntfy)
- **Risk tools**: `store_risk_status`
- **Shared API**: Both profile and snapshot tools use `kind` + `id` + optional `region`; snapshot tools add time fields
- **Profile kinds**: countries, stocks, etfs, crypto, indices, sources, commodities, crops, materials, products, companies
- **Regions**: north_america, latin_america, europe, mena, sub_saharan_africa, south_asia, east_asia, southeast_asia, central_asia, oceania, arctic, antarctic, global

#### Data Domains (12 namespaces)
- All use FastMCP framework + `httpx` for HTTP calls
- Most APIs are free/no-key; some need optional API keys (FRED, ACLED, EIA, etc.)

### deploy.conf (Central Config)
All scripts source this file. Key variables:
- `UBER_USER=augur`, `UBER_HOST=augur.uber.space`
- `GH_USER=ManuelKugelmann`, `GH_REPO=Augur`
- `STACK_DIR=$HOME/augur`, `APP_DIR=$HOME/LibreChat`, `BACKUP_DIR=$HOME/backups/mongo`
- `LC_PORT=3080`, `NODE_VERSION=22`

### Python Dependencies
```
fastmcp>=3.1
httpx>=0.27
pymongo>=4.7
python-dotenv>=1.0
pandas>=2.0
ta>=0.10
```

## Dev & Deploy Workflow

### Development
1. Edit code locally or in Claude Code
2. Push to `main` branch
3. On Uberspace: `augur pull` (git pull + restart)

### Production Release
1. Tag: `git tag v0.2.0 && git push --tags`
2. CI builds `librechat-bundle.tar.gz` → GitHub Release
3. On Uberspace: `augur u` (downloads release, atomic swap, restarts)
4. Rollback if needed: `augur rb`

### First Deploy (one-liner)
```bash
curl -sL https://raw.githubusercontent.com/ManuelKugelmann/Augur/main/librechat-uberspace/scripts/Augur.sh | bash
```
Auto-detects fresh install (no repo cloned → runs `install`). Clones repo, creates venv, registers services, installs LibreChat (release bundle or repo fallback), sets up `augur` shortcut. Re-run safe via `augur install`.

### Tagging from GitHub Web UI
Releases → Draft a new release → Choose a tag → type `v0.1.0` → Create new tag on publish → Publish release

## `augur` Command Reference

```
augur help        show all commands
augur s|status    service status + version + host
augur r|restart   restart LibreChat
augur l|logs      tail service logs
augur testrun     run LibreChat in foreground (see errors directly)
augur v|version   show installed version
augur u|update    update from latest GitHub release
augur pull        quick dev update via git pull
augur install     re-run full installer (idempotent)
augur rb|rollback rollback to previous version
augur backup      backup MongoDB to ~/backups/mongo/ (rolling)
augur restore [f] restore MongoDB from backup (latest if no file)
augur backups     list available backups
augur env         edit LibreChat .env
augur yaml        edit librechat.yaml
augur conf        edit deploy.conf
```

## Profiles

**Target scale: 1000+ profiles.** All profiles stored in MongoDB (`profiles_{kind}` collections).
Profiles describe anything tradeable or trade-relevant. Organized by kind + region.

### Kinds

| Kind | ID convention | Example |
|------|---------------|---------|
| `countries` | ISO3 uppercase | `DEU`, `USA` |
| `stocks` | Ticker uppercase | `AAPL`, `NVDA` |
| `etfs` | Ticker uppercase | `VWO`, `SPY` |
| `crypto` | Symbol uppercase | `BTC`, `ETH` |
| `indices` | Symbol uppercase | `SPX`, `NDX` |
| `commodities` | lowercase slug | `crude_oil`, `gold` |
| `crops` | lowercase slug | `corn`, `soybeans` |
| `materials` | lowercase slug | `lithium`, `copper` |
| `products` | lowercase slug | `semiconductors`, `ev_batteries` |
| `companies` | lowercase slug | `tsmc`, `aramco` |
| `sources` | lowercase slug | `faostat`, `open-meteo` |

### Regions

north_america, latin_america, europe, mena, sub_saharan_africa, south_asia, east_asia, southeast_asia, central_asia, oceania, arctic, antarctic, global

### Profile tools

| Tool | Purpose |
|------|---------|
| `get_profile(kind, id, region?)` | Read a profile |
| `put_profile(kind, id, data, region?)` | Create/merge (default: global) |
| `list_profiles(kind, region?)` | List profiles, optionally by region |
| `find_profile(query, region?)` | Cross-kind search by name/ID/tag |
| `search_profiles(kind, field, value, region?)` | Field-level search |
| `list_regions()` | List regions and their kinds |
| `lint_profiles(kind?, id?)` | Validate required fields (id, name) |

### Snapshot tools (same API + time fields)

| Tool | Purpose |
|------|---------|
| `snapshot(kind, entity, type, data, region?, ...)` | Store timestamped data in snap_{kind} |
| `history(kind, entity, type?, region?, after?, before?)` | Query snapshot history |
| `trend(kind, entity, type, field, periods?)` | Extract field trend |
| `nearby(kind, lon, lat, max_km?, type?)` | Geo proximity search |
| `event(subtype, summary, data, region?, ...)` | Log signal event |
| `recent_events(subtype?, severity?, region?, ...)` | Query recent events |
| `archive_snapshot(kind, entity, type, data, region?)` | Long-term storage in arch_{kind} |
| `archive_history(kind, entity, type?, region?, ...)` | Query archive |
| `compact(kind, entity, type, older_than_days?)` | Downsample to archive |
| `aggregate(kind, pipeline, archive?)` | Raw aggregation pipeline |
| `chart(kind, entity, type, fields, ...)` | Generate Plotly chart |

### Notes tools (per-user, same API + user scoping)

| Tool | Purpose |
|------|---------|
| `save_note(title, content, tags?, kind?)` | Save note/plan/watchlist/journal (scoped to user) |
| `get_notes(kind?, tag?, limit?)` | List your notes, filter by kind or tag |
| `update_note(note_id, content?, title?, tags?)` | Update a note (owner only) |
| `delete_note(note_id)` | Delete a note (owner only) |

Note kinds: `note` (default), `plan`, `watchlist`, `journal` — use `kind` to organize.

### Research tools (shared, no user tracking)

| Tool | Purpose |
|------|---------|
| `save_research(title, content, tags?, kind?)` | Save shared research note (upsert by title) |
| `get_research(title?, tag?, kind?, limit?)` | List shared research notes |
| `update_research(title, content?, tags?)` | Update shared research by title |
| `delete_research(title)` | Delete shared research by title |

Research kinds: `research` (default), `report`, `briefing`, `alert`

### Notifications (ntfy)

| Tool | Purpose |
|------|---------|
| `notify(title, message, priority?, tags?)` | Send push notification via ntfy (per-user topic) |

Per-user topic via `X-Ntfy-Topic` header (customUserVars). Fallback: `NTFY_TOPIC` env var.

### Risk gate

| Tool | Purpose |
|------|---------|
| `risk_status()` | Show actions used today, daily limit, remaining |

Internal: `_risk_check(action, params, dry_run=True)` — called before any external trading API call. Blocks if user not identified, dry_run=True (default), or daily limit exceeded.

## Environment Variables

### Signals Stack (`.env`)
- `MONGO_URI_SIGNALS` — MongoDB Atlas connection string (database: `signals`). **Not** the same as LibreChat's `MONGO_URI`.
- `PROFILES_DIR` — path to profiles directory (default: `./profiles`)
- `MCP_TRANSPORT` — `streamable-http` (production) or `stdio` (dev/testing, default)
- `MCP_PORT` — port for streamable-http (default: `8071`)
- `RISK_DAILY_LIMIT` — max trading actions per user per day (default: `50`)
- `NTFY_BASE_URL` — ntfy server URL (default: `https://ntfy.sh`)
- `NTFY_TOPIC` — server-wide fallback ntfy topic (per-user via `X-Ntfy-Topic` header)
- Optional API keys: `FRED_API_KEY`, `ACLED_API_KEY`, `EIA_API_KEY`, `COMTRADE_API_KEY`, `GOOGLE_API_KEY`, `AISSTREAM_API_KEY`, `CF_API_TOKEN`, `USDA_NASS_API_KEY`, `IDMC_API_KEY`
- Full reference: `docs/api-keys.md`

### LibreChat (`~/LibreChat/.env`)
- `MONGO_URI` — MongoDB Atlas connection string (database: `LibreChat`)
- `CREDS_KEY`, `CREDS_IV`, `JWT_SECRET`, `JWT_REFRESH_SECRET` — auto-generated by setup.sh
- LLM keys: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `OPENROUTER_API_KEY`
- `SEARCH=false` (Meilisearch disabled)

## Current Status (see TODO.md)

**Completed**: Repo init, cleanup, LibreChat full integration, CI release workflow, `augur` ops tool, data repo automation, code review fixes (security + correctness), chart tool + HTTP endpoint, profile INDEX.json, API keys doc, setup doc, test suite (550+ tests: ~140 bats + ~420 pytest) + CI

**Next priorities (P0)**:
- Validate combined trading server runs without errors (store + 12 domains)
- Test signals store against live Atlas M0
- Populate profiles at scale (~200 countries, ~500 stocks, ~100 ETFs, ~75 sources)

**Not yet done**: End-to-end Uberspace deployment test (P4), periodic ingest scheduler (P1), alert/threshold system (P1)

## Testing

### Frameworks
- **Shell scripts**: [bats-core](https://github.com/bats-core/bats-core) (Bash Automated Testing System) — ~140 tests across `.bats` files
- **Python**: [pytest](https://docs.pytest.org/) — ~420 tests across `test_*.py` files
- **Total**: ~560 tests

### Running Tests
```bash
# Run fast shell tests (no venv creation, runs in seconds)
bats tests/test_bootstrap.bats tests/test_deploy_conf.bats \
     tests/test_setup.bats tests/test_ta_cron.bats \
     tests/test_ta_dispatch.bats

# Run slow install tests (creates venvs, runs full install scripts)
bats tests/test_install_smoke.bats tests/test_install_lifecycle.bats

# Run all shell tests
bats tests/*.bats

# Run all Python tests
python -m pytest tests/ -v

# Run everything
bats tests/*.bats && python -m pytest tests/ -v

# Run a specific bats file
bats tests/test_ta_cron.bats

# Syntax check only (fast)
bash -n librechat-uberspace/scripts/Augur.sh
```

### Sandbox (Claude Code) Workarounds

The `ta` library (technical analysis) has a setuptools compatibility issue in sandbox environments. Install with:
```bash
SETUPTOOLS_USE_DISTUTILS=stdlib pip install ta --no-build-isolation
```

If `ta` is not installed, `test_indicators.py` and `TestCombinedServer` in `test_servers.py` are automatically skipped.

If `httpx` is not installed, `TestEdgeResolution` in `test_agents_seed.py` and all integration tests (`test_integration_free.py`, `test_integration_keyed.py`) are automatically skipped. Install with:
```bash
pip install httpx
```

Bats tests require `/dev/fd` (process substitution). If `/dev/fd` is missing (common in containers), create the symlink:
```bash
ln -sf /proc/self/fd /dev/fd
```

### Test Architecture

**Shell tests (bats)**:
- Each test gets a **sandboxed `$HOME`** via `mktemp -d` — no side effects on the real system
- External commands (`supervisorctl`, `uberspace`, `hostname`, `crontab`) are **stubbed** with scripts prepended to `$PATH`
- Git operations use **local bare repos** as fake remotes (no network needed)
- SSH keys may be needed for git operations in some test contexts
- `$REAL_GIT` is saved before stubbing so git stubs can delegate non-intercepted calls

**Python tests (pytest)**:
- `conftest.py` mocks `pymongo` and `fastmcp` at import time — no MongoDB or MCP runtime needed
- Tests exercise pure-Python profile, index, lint, and search logic from `src/store/server.py`
- Each test gets a **temporary profiles directory** via `tmp_path` fixture with `monkeypatch`

### Test Coverage

| File | Tests | Framework | Covers |
|------|-------|-----------|--------|
| `test_store.py` | 66 | pytest | Profile CRUD, region discovery, path safety, index build/update, find/search, lint, schema validation, notes, shared research |
| `test_indicators.py` | 7 | pytest | Composite signal logic (analyze_full), Yahoo OHLCV fetch, SMA(50) fallback, error handling |
| `test_ta_dispatch.bats` | 10 | bats | `augur help`, `status`, `version`, `restart`, `rollback`, aliases |
| `test_setup.bats` | 11 | bats | Install/update modes, `.env` generation, `librechat.yaml` templating, Node.js version check, uploads preservation, rollback |
| `test_ta_cron.bats` | 1 | bats | Cron hook done message |
| `test_install_smoke.bats` | 6 | bats | Full install artifacts, idempotency, cron-after-install, LC bundle download (slow, path-filtered CI) |
| `test_deploy_conf.bats` | 5 | bats | Config loading, env overrides, variable defaults |
| `test_install_lifecycle.bats` | 4 | bats | Pull workflow, cron import check, full install→pull→update lifecycle (slow, path-filtered CI) |
| `test_bootstrap.bats` | 2 | bats | Syntax validation for all `.sh` files |

### CI Integration
**`tests.yml`** — Runs on every push to `main` and on PRs:
- **shell-tests** job: installs bats, runs `bash -n` on all `.sh` files, then fast bats tests (excludes install tests)
- **python-tests** job: sets up Python 3.11, installs pytest, runs `pytest tests/`
- **shellcheck** job: runs ShellCheck at error severity on all scripts

**`tests-install.yml`** — Runs only when install-related files change (`librechat-uberspace/scripts/**`, `deploy.conf`, `requirements.txt`, `tests/test_install_*`):
- **install-tests** job: runs `test_install_smoke.bats` + `test_install_lifecycle.bats` (creates real venvs, slow)

### Writing New Tests

**Bats (shell)**:
1. Create `tests/test_<name>.bats`
2. Load helpers: `load helpers/setup`
3. Use `setup()` / `teardown()` with `setup_sandbox` / `teardown_sandbox`
4. Stub external commands with `stub_command "name" "body"` or write to `$STUBS_DIR/`
5. Use `init_mock_git_repo "$dir"` to create test git repos
6. Run `bats tests/test_<name>.bats` to verify

**Pytest (Python)**:
1. Add tests to `tests/test_store.py` (or create new `tests/test_<name>.py`)
2. Use the `profiles_dir` fixture for a temp profiles directory
3. Use the `store` fixture for access to `server.py` functions
4. Run `python -m pytest tests/test_<name>.py -v` to verify

## Conventions

- All shell scripts use `set -euo pipefail`
- All scripts load `deploy.conf` as first step
- Color output: green=success, yellow=warning, red=error, cyan=info
- Profile files: uppercase ISO codes for countries (DEU, USA), uppercase tickers for entities (AAPL, NVDA)
- Git tags: `vMAJOR.MINOR.PATCH` (triggers CI release)
- Cron logger tag: `augur-cron`
- `__HOME__` placeholder in `librechat.yaml` is replaced by `setup.sh` with actual `$HOME`
- After editing any `.sh` file, always run `bash -n <file>` to verify syntax — especially for `Augur.sh` which must work when piped via `curl | bash` (avoid complex nested quoting in that context)
- Use approximate tool counts (e.g. "50+ tools") instead of exact numbers — exact counts go stale as tools are added/removed
