# CLAUDE.md — Project context for Claude Code

## Rules

- **Never circumvent or exclude failing tests.** Always find and fix the root cause. If not possible, discuss the problem with the user before proceeding.
- **Run tests locally before pushing.** Always run `python -m pytest tests/ -v` (and `bats tests/*.bats` if shell scripts changed) before committing and pushing. Do not push code that fails tests. For long-running test suites (e.g. `bats tests/install/*.bats`), push first to leverage CI, then run locally in parallel.
- **Prefer battle-tested libraries over custom code.** Use well-established libraries (e.g. `mongomock` for MongoDB mocks) instead of writing custom implementations — but don't explode the dependency tree for marginal gains.

## Project

**Augur** — An MCP-based trading signals platform deployed via LibreChat on Uberspace. 1 combined trading server (signals store + 12 data domains + technical indicators, 50+ tools, 75+ data sources) via streamable-http + external MCPs (finance, gdelt-cloud, prediction-markets, rss, reddit, alphavantage, hackernews, arxiv, math, regression, crypto-sentiment). Single process, multi-user: OSINT data is shared, notes/plans are per-user, trading keys are per-user via `customUserVars`. A risk gate guards all external trading actions.

## Key Names & Paths

- **Repo**: `ManuelKugelmann/Augur`
- **Ops CLI**: `Augur.sh` → installed as `~/bin/augur` (symlink `~/bin/Augur`)
- **Uberspace host**: `augur.uber.space` (`UBER_USER=augur`)
- **Platform**: U8 (Arch Linux / systemd). U7 (CentOS 7 / supervisord) dormant but code paths remain.
- **deploy.conf**: Central config sourced by all scripts. Key vars: `GH_USER`, `GH_REPO`, `STACK_DIR=$HOME/augur`, `APP_DIR=$HOME/LibreChat`, `LC_PORT=3080`

| Uberspace Path | Purpose |
|------|---------|
| `~/augur/` | Clone of this repo (signals stack) |
| `~/LibreChat/` | LibreChat installation (from CI release bundle) |
| `~/backups/mongo/` | Rolling MongoDB backups |

## Architecture

```
GitHub (Augur) ──tag──▶ CI builds bundle ──▶ GitHub Release
                                                   │
                                                   ▼
                         Uberspace (augur.uber.space)
                         ├─ LibreChat (:3080, Node.js)
                         │   ├─ MCP: trading ──streamable-http──▶ :8071/mcp
                         │   ├─ MCP: Tier 1 (finance, gdelt, predictions, rss, reddit)
                         │   └─ MCP: Tier 2 (alphavantage, hackernews, arxiv, math, etc.)
                         ├─ trading server (:8071, Python, store + 12 domains, 50+ tools)
                         └─ cron → MongoDB Atlas + 75+ free data APIs
```

### Combined Trading Server (`src/servers/combined_server.py`)
- Signals store + 12 data domains + technical indicators combined via FastMCP `mount(namespace=)`
- Transport: streamable-http on `:8071/mcp`, falls back to stdio for dev/testing
- Tool namespacing: `store_get_profile`, `weather_forecast`, `econ_fred_series`, `ta_analyze_full`, etc.
- Multi-user: `X-User-ID`/`X-User-Email` headers from LibreChat; notes/plans per-user; broker keys per-user via headers
- Risk gate: `_risk_check()` enforces dry_run default, daily action limits

### Signals Store (store_* namespace)
- **Profiles**: MongoDB `profiles_{kind}` collections (text + geo indexes). Kinds: countries, stocks, etfs, crypto, indices, sources, commodities, crops, materials, products, companies
- **Snapshots**: Per-kind timeseries (`snap_{kind}`, `arch_{kind}`, `events`). Tools: snapshot, history, trend, nearby, event, compact, aggregate, chart
- **Notes** (per-user): plans, watchlists, journals in `user_notes` collection
- **Research** (shared): `save_research`, `get_research`, `update_research`, `delete_research`
- **Regions**: north_america, latin_america, europe, mena, sub_saharan_africa, south_asia, east_asia, southeast_asia, central_asia, oceania, arctic, antarctic, global
- **ID conventions**: countries=ISO3 (`DEU`), stocks/etfs/crypto/indices=ticker (`AAPL`), others=lowercase slug (`crude_oil`)

## Dev & Deploy Workflow

```bash
# Development: push to main, then on Uberspace:
augur pull                    # git pull + restart

# Production: tag → CI → release bundle
git tag v0.2.0 && git push --tags
augur u                       # downloads release, atomic swap, restarts
augur rb                      # rollback if needed

# Fresh install (one-liner):
curl -sL "https://raw.githubusercontent.com/ManuelKugelmann/Augur/main/augur-uberspace/install.sh?$(date +%s)" | bash
```

## Environment Variables

### Signals Stack (`~/augur/.env`)
- `MONGO_URI_SIGNALS` — MongoDB Atlas (database: `signals`). **Not** the same as LibreChat's `MONGO_URI`.
- `MCP_TRANSPORT` — `streamable-http` (prod) or `stdio` (dev, default)
- `MCP_PORT` — default `8071`
- Optional API keys: `FRED_API_KEY`, `ACLED_API_KEY`, `EIA_API_KEY`, `COMTRADE_API_KEY`, `GOOGLE_API_KEY`, `AISSTREAM_API_KEY`, `CF_API_TOKEN`, `USDA_NASS_API_KEY`, `IDMC_API_KEY` — see `docs/api-keys.md`

## Testing

~560 tests: bats (shell) + pytest (Python).

```bash
# Fast shell tests
bats tests/test_bootstrap.bats tests/test_deploy_conf.bats \
     tests/test_setup.bats tests/test_ta_cron.bats \
     tests/test_ta_dispatch.bats

# All Python tests
python -m pytest tests/ -v

# Everything
bats tests/*.bats && python -m pytest tests/ -v

# Syntax check
bash -n Augur.sh
```

### Sandbox Workarounds
- `ta` library: `SETUPTOOLS_USE_DISTUTILS=stdlib pip install ta --no-build-isolation`
- Missing `ta` or `httpx` → related tests auto-skip
- Missing `/dev/fd`: `ln -sf /proc/self/fd /dev/fd`

### Test Architecture
- **Bats**: sandboxed `$HOME` via `mktemp -d`, external commands stubbed, git uses local bare repos. `$REAL_GIT` saved before stubbing.
- **Pytest**: `conftest.py` mocks `pymongo`/`fastmcp` at import time. `profiles_dir` + `store` fixtures.
- **CI**: `tests.yml` (push/PR: shell + python + shellcheck), `tests-install.yml` (slow install tests, path-filtered)

## Conventions

- All shell scripts: `set -euo pipefail`, source `deploy.conf` first
- Profile IDs: uppercase ISO/tickers for countries/stocks, lowercase slugs for others
- Git tags: `vMAJOR.MINOR.PATCH` (triggers CI release)
- Cron logger tag: `augur-cron`
- `__HOME__` in `librechat.yaml` replaced by `setup.sh` with actual `$HOME`
- After editing `.sh` files, run `bash -n <file>` — especially `Augur.sh` (must work via `curl | bash`)
- Use approximate tool counts (e.g. "50+ tools") — exact counts go stale
