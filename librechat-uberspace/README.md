LibreChat deployment with MCP server (50+ tools): 1 combined trading server (signals store + 12 data domains, 75+ data sources) via streamable-http. Single process, multi-user. No Docker, no Meilisearch, no RAG, no Redis.

All scripts read from `deploy.conf` — edit once, applies everywhere.

## Architecture

```
┌──────────────┐     ┌────────┐     ┌───────────┐     ┌──────────────────────────────┐
│ Codespace/WSL│────▶│ GitHub │────▶│ CI Release │────▶│ augur.uber.space           │
│ dev + test   │push │  repo  │tag  │ build+tar  │pull │                             │
└──────────────┘     └────────┘     └───────────┘     │ LibreChat (:3080)           │
                                                       │ └─ MCP: trading ──http──▶   │
                                                       │                             │
                                                       │ trading server (:8071, 68t) │
                                                       │ ├─ shared: OSINT data       │
                                                       │ ├─ per-user: notes, risk    │
                                                       │ └─ per-user: broker keys    │
                                                       │                             │
                                                       │ git-sync cron ──push──▶ GitHub (private)
                                                       └─────────────────────────────┘
                                                              │
                                              ┌───────────────┼──────────┐
                                              ▼               ▼          ▼
                                       MongoDB Atlas    Cloud LLMs    75+ APIs
                                       (free tier)      (your keys)   (free data)
```

## Configuration

All deployment settings live in one file at the repo root:

```bash
cat deploy.conf
```

| Variable | Default | Purpose |
|----------|---------|---------|
| `UBER_USER` | `augur` | Uberspace username |
| `UBER_HOST` | `augur.uber.space` | Uberspace hostname |
| `GH_USER` | `ManuelKugelmann` | GitHub username |
| `GH_REPO` | `Augur` | Signals stack repo |
| `STACK_DIR` | `$HOME/augur` | Signals stack path |
| `APP_DIR` | `$HOME/LibreChat` | LibreChat path |
| `LC_PORT` | `3080` | LibreChat port |
| `NODE_VERSION` | `22` | Node.js version |

Override any value via environment: `UBER_USER=other augur install`

## QuickStart

### Prerequisites

| What | Where | Cost |
|------|-------|------|
| Uberspace account | https://uberspace.de | ~5 EUR/mo |
| MongoDB Atlas M0 | https://cloud.mongodb.com | Free |
| LLM API key | Any provider (many free tiers) | Per-use |
| GitHub account | https://github.com | Free |

### Step 1: MongoDB Atlas (5 min)

1. Go to https://cloud.mongodb.com → Create free M0 cluster
2. Create a database user (username + password)
3. Network Access → Add `0.0.0.0/0` (Uberspace has no static IP)
4. Click Connect → copy connection string:
   ```
   mongodb+srv://youruser:yourpass@cluster0.xxxxx.mongodb.net/LibreChat
   ```

### Step 2: Deploy to Uberspace (one-liner)

SSH into your Uberspace host:

```bash
ssh augur@augur.uber.space
```

Then run the installer:

```bash
curl -sL "https://raw.githubusercontent.com/ManuelKugelmann/Augur/main/Augur.sh?$(date +%s)" | bash
```

This clones the repo, creates Python venv, installs LibreChat (release bundle or git fallback), registers supervisord services (`librechat`, `trading`, `charts`), and sets up the `augur` command. Re-run safe.

### Step 3: Configure (2 min)

```bash
# Signals stack — set MONGO_URI_SIGNALS
nano ~/augur/.env

# LibreChat — set MONGO_URI + at least one LLM key
nano ~/LibreChat/.env
```

### Step 4: Start

```bash
supervisorctl start librechat
supervisorctl start trading
augur status
```

### Step 5: Access

```
https://augur.uber.space
```

Register your first user → that becomes the admin account.

## Multi-User

The trading server runs as a single process on `:8071` via `streamable-http`.
LibreChat injects per-user headers on every MCP request:

- `X-User-ID` / `X-User-Email` — user identification
- `X-Broker-Key` / `X-Broker-Secret` / `X-Broker-Name` — per-user trading keys
- `X-Risk-Daily-Limit` / `X-Risk-Live-Trading` — per-user risk settings

Users configure their own settings in **LibreChat Settings → Plugins → trading**.

### Shared vs per-user

| Shared (OSINT) | Per-user |
|----------------|----------|
| Profiles (JSON files) | Notes/plans (MongoDB `user_notes`) |
| 12 data domain tools | Broker API keys (HTTP headers only) |
| Snapshots/events (tagged with user_id) | Risk gate (daily limit, live trading) |

## MCP Servers

### Trading (streamable-http, single process)

One combined Python server exposing 50+ tools via FastMCP 3.1+ `mount()`:

| Namespace | Purpose |
|---|---|
| `store_*` | Profiles, snapshots, notes, charts, risk gate |
| 12 data domains | Weather, disaster, econ, agri, conflict, commodity, health, politics, humanitarian, transport, water, infra |

## Day-to-Day Operations

```bash
augur help       # show all commands
augur s|status   # status + version + host
augur l|logs     # tail logs
augur r|restart  # restart LibreChat
augur v|version  # show version
augur u|update   # update from latest GitHub release
augur pull       # quick update via git pull (dev)
augur install    # re-run full installer (idempotent)
augur rb|rollback # rollback to previous version
augur sync       # force git sync of data
augur check      # health check
augur check -t   # health check + test suite
augur env        # edit .env
augur yaml       # edit librechat.yaml
augur conf       # edit deploy.conf
```

## Updates

| Method | Command | Use when |
|--------|---------|----------|
| Git pull | `augur pull` | Dev/staging — fast, no release needed |
| Release | `augur u` | Production — downloads tagged release bundle |
| Re-install | `augur install` | Full re-setup (idempotent, preserves config) |

```bash
# Dev: push → pull
git push                     # from dev machine
augur pull                      # on Uberspace

# Production: tag → release → deploy
git tag v0.3.0 && git push --tags
augur u                         # on Uberspace
```

## Resource Limits (Uberspace)

| Resource | Limit | Usage |
|---|---|---|
| RAM | 1.5 GB hard kill | ~500-800 MB (LibreChat) + ~80 MB (trading) |
| Storage | 10 GB (expandable) | ~2 GB installed |
| Node.js | 18, 20, 22 | Requires >=20 |
| Docker | Not available | Not needed |

## Cost

| Service | Cost |
|---|---|
| Uberspace | ~5 EUR/mo (pay what you want, min 1 EUR) |
| MongoDB Atlas | Free (shared tier, 512 MB) |
| Cloud LLMs | Per-use (your API keys, many free tiers) |
| GitHub | Free |
| **Total** | **~5 EUR/mo + LLM usage** |

## Full Guide

See [docs/librechat-uberspace-setup.md](../docs/librechat-uberspace-setup.md) for the complete walkthrough with troubleshooting, security checklist, and architecture details.
