# CLAUDE.md — Project context for Claude Code

## Rules

- **Never circumvent or exclude failing tests.** Find and fix root causes.
- **Run tests before pushing.** `python -m pytest tests/ -v` (+ `bats tests/*.bats` if shell changed). For slow suites (`bats tests/install/*.bats`), push first to leverage CI.
- **Prefer battle-tested libraries** over custom code (e.g. `mongomock` for MongoDB mocks).
- **Keep MCP packages pinned** to `~/bin/` — don't rely on `npx` for production MCPs.

## Project

**Augur** — MCP-based trading signals platform on LibreChat/Uberspace. Combined trading server (store + 12 domains + indicators, 50+ tools, 75+ sources) via streamable-http + external MCPs (finance, gdelt-cloud, prediction-markets, rss, reddit, hackernews, arxiv, math, regression, crypto-sentiment). Single process, multi-user. Risk gate guards all trading actions.

## Key Paths

| Path | Purpose |
|------|---------|
| `Augur.sh` → `~/bin/augur` | Ops CLI |
| `~/augur/` | This repo (signals stack) |
| `~/LibreChat/` | LibreChat (from CI release bundle) |
| `~/backups/mongo/` | Rolling MongoDB backups |
| `deploy.conf` | Config: `GH_USER`, `GH_REPO`, `STACK_DIR`, `APP_DIR`, `LC_PORT=3080` |

**Host**: `augur.uber.space` (U8, Arch Linux, systemd)

## Architecture

```
GitHub ──tag──▶ CI bundle ──▶ Release ──▶ Uberspace
├─ LibreChat (:3080) → MCP: trading ──streamable-http──▶ :8071/mcp
│                    → MCP: Tier 1 (finance, gdelt, predictions, rss, reddit)
│                    → MCP: Tier 2 (hackernews, arxiv, math, regression, crypto-sentiment)
├─ trading server (:8071, Python, store + 12 domains, 50+ tools)
└─ cron → MongoDB Atlas + 75+ free data APIs
```

**Trading server** (`src/servers/combined_server.py`): FastMCP `mount(namespace=)`, streamable-http `:8071/mcp`, stdio for dev. Namespaces: `store_*`, `weather_*`, `econ_*`, `ta_*`, etc. Multi-user via `X-User-ID`/`X-User-Email` headers.

**Store** (`store_*`): MongoDB `profiles_{kind}` (12 kinds), `snap_{kind}`/`arch_{kind}`/`events` timeseries. Notes per-user, research shared. IDs: ISO3 for countries, tickers for stocks, lowercase slugs for others.

## Environment (`~/augur/.env`)

`MONGO_URI_SIGNALS` (Atlas, `signals` db), `MCP_TRANSPORT` (`streamable-http`/`stdio`), `MCP_PORT` (`8071`). Optional API keys: `FRED_API_KEY`, `ACLED_API_KEY`, `EIA_API_KEY`, `COMTRADE_API_KEY`, `GOOGLE_API_KEY`, `AISSTREAM_API_KEY`, `CF_API_TOKEN`, `USDA_NASS_API_KEY`, `IDMC_API_KEY` — see `docs/api-keys.md`.

## Testing

```bash
python -m pytest tests/ -v             # Python tests
bats tests/*.bats                      # shell tests
bash -n Augur.sh                       # syntax check after .sh edits
```

**Sandbox workarounds**: `SETUPTOOLS_USE_DISTUTILS=stdlib pip install ta --no-build-isolation`; missing `ta`/`httpx` → tests auto-skip; `ln -sf /proc/self/fd /dev/fd` if needed.

**Test arch**: Bats uses sandboxed `$HOME`, stubbed commands, local bare repos. Pytest mocks `pymongo`/`fastmcp` at import via `conftest.py`. CI: `tests.yml` (push/PR), `tests-install.yml` (slow, path-filtered).

## Conventions

- Shell: `set -euo pipefail`, source `deploy.conf` first
- IDs: uppercase ISO/tickers (countries/stocks), lowercase slugs (others)
- Tags: `vMAJOR.MINOR.PATCH` triggers CI release
- `__HOME__` in `librechat.yaml` → replaced by `setup.sh`
- After editing `.sh` files: `bash -n <file>`
- Use approximate tool counts (e.g. "50+ tools")
- Deploy: `augur u` (update) or `curl -sL ".../install.sh?$(date +%s)" | bash` (fresh)
