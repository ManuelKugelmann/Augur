# CLAUDE.md — Project context for Claude Code

## Rules

- **Never circumvent or exclude failing tests.** Find and fix root causes.
- **Run tests before pushing.** `python -m pytest tests/ -v` (+ `bats tests/*.bats` if shell changed). For slow suites (`bats tests/install/*.bats`), push first to leverage CI.
- **Prefer battle-tested libraries** over custom code (e.g. `mongomock` for MongoDB mocks).
- **Keep MCP packages pinned** to `~/bin/` — don't rely on `npx` for production MCPs.
- **A pasted log snippet can contain more than one error.** Fix all of them, not just the first.

## Project

**Augur** — MCP-based trading signals platform on LibreChat/Uberspace. Combined trading server (store + 12 domains + indicators, 50+ tools, 75+ sources) via streamable-http + external MCPs. Single process, multi-user. Risk gate guards all trading actions.

## Architecture

```
GitHub ──tag──▶ CI bundle ──▶ Release ──▶ Uberspace
├─ LibreChat (:3080) → MCP: trading (:8071), Tier 1 & 2 MCPs
├─ trading server (:8071, FastMCP, store + 12 domains, 50+ tools)
├─ CLIProxyAPI (:8317, optional) → Claude Max subscription proxy
└─ cron → MongoDB Atlas + 75+ free data APIs
```

**Trading server** (`src/servers/combined_server.py`): FastMCP `mount(namespace=)`, streamable-http `:8071/mcp`, stdio for dev. Namespaces: `store_*`, `weather_*`, `econ_*`, `ta_*`, etc. Multi-user via `X-User-ID`/`X-User-Email` headers.

**Store** (`store_*`): MongoDB `profiles_{kind}` (12 kinds), `snap_{kind}`/`arch_{kind}`/`events` timeseries. Notes per-user, research shared. IDs: ISO3 for countries, tickers for stocks, lowercase slugs for others.

## Key Paths & Config

| Path | Purpose |
|------|---------|
| `Augur.sh` → `~/bin/augur` | Ops CLI |
| `~/augur/` | This repo (signals stack) |
| `~/LibreChat/` | LibreChat (from CI release bundle) |
| `deploy.conf` | Config: `GH_USER`, `GH_REPO`, `STACK_DIR`, `APP_DIR`, `LC_PORT=3080` |
| `~/augur/.env` | `MONGO_URI_SIGNALS`, `MCP_TRANSPORT`, `MCP_PORT=8071`, API keys (see `docs/api-keys.md`) |
| `~/.claude-auth.env` | CLIProxyAPI OAuth token (`CLAUDE_CODE_OAUTH_TOKEN`) |
| `~/.cli-proxy-api/config.yaml` | CLIProxyAPI config (port 8317) |

**Host**: Uberspace U8 (Arch Linux, systemd). Username = subdomain (auto-detected via `$(whoami).uber.space`).

**CLIProxyAPI**: Optional OpenAI-compatible proxy for Claude Pro/Max subscriptions. `augur proxy setup|start|stop|status|test|token`. Docs: `docs/claude-token-wrapper.md`.

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
- Deploy: `augur update` or `curl -sL ".../install.sh?$(date +%s)" | bash` (fresh)
