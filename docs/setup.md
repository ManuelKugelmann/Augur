# Setup Guide

Single-source setup for Augur — local dev or Uberspace production.

---

## Prerequisites

| What | Where | Cost |
|------|-------|------|
| MongoDB Atlas M0 | https://cloud.mongodb.com | Free (512 MB) |
| LLM API key | OpenRouter / Anthropic / OpenAI | Per-use |
| Python 3.11+ | System or pyenv | Free |
| **Production only:** Uberspace | https://uberspace.de | ~5 EUR/mo |
| **Production only:** GitHub account | https://github.com | Free |

## 1. MongoDB Atlas (5 min)

1. Go to https://cloud.mongodb.com and sign up
2. Create organization > project > **Build a Database**
3. Choose **M0 (Free)** — shared tier, 512 MB, pick region closest to you
4. Create a database user (username + strong password)
5. **Network Access** > Add IP Address:
   - Local dev: add your IP or `0.0.0.0/0`
   - Uberspace: `0.0.0.0/0` (no static IP, auth via connection string)
6. **Connect** > Drivers > copy URI, replace `<password>`:

```
mongodb+srv://youruser:yourpass@cluster0.xxxxx.mongodb.net/signals
```

Both the signals store and LibreChat share this cluster (different database names: `signals` and `LibreChat`).

## 2. API Keys

See **[docs/api-keys.md](api-keys.md)** for the full reference with signup links.

Quick summary — only `MONGO_URI_SIGNALS` is required. Everything else is optional:

```bash
# Required
MONGO_URI_SIGNALS=mongodb+srv://user:pass@cluster0.xxxxx.mongodb.net/signals

# Recommended (most useful, instant free signup)
FRED_API_KEY=           # https://fred.stlouisfed.org/docs/api/api_key.html
EIA_API_KEY=            # https://www.eia.gov/opendata/register.php

# Other optional keys (all free)
ACLED_API_KEY=          # https://acleddata.com/register/
ACLED_EMAIL=
COMTRADE_API_KEY=       # https://comtradeplus.un.org/TradeFlow
GOOGLE_API_KEY=         # https://console.cloud.google.com/apis/credentials
AISSTREAM_API_KEY=      # https://aisstream.io/
CF_API_TOKEN=           # https://dash.cloudflare.com/profile/api-tokens
USDA_NASS_API_KEY=      # https://quickstats.nass.usda.gov/api/
```

28 of the 75+ data sources need zero keys and work out of the box.

---

## Local Development

```bash
git clone https://github.com/ManuelKugelmann/Augur.git
cd Augur
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # edit: set MONGO_URI_SIGNALS + optional API keys
python src/servers/combined_server.py  # all tools (store + 12 domains)
```

Run individual servers standalone for testing:

```bash
python src/store/server.py             # signals store only
python src/servers/weather_server.py   # no key needed
python src/servers/macro_server.py     # needs FRED_API_KEY for FRED tools
```

---

## Uberspace Deploy — Two Modes

| Mode | Command | LibreChat source | Update command | Use when |
|------|---------|-----------------|----------------|----------|
| **Release** | `augur install` | Tagged release bundle from CI | `augur u` | Production — stable, pre-tested |
| **Dev** | `augur install dev` | CI prebuilt artifact or git clone + build | `augur pull` | Development — fast iteration, no tags needed |

Both modes use the same one-liner entry point. The only difference is where LibreChat comes from.

---

### Dev Mode Walkthrough (prebuilt LibreChat + git)

Dev mode skips tagged releases and instead uses a **CI-prebuilt LibreChat** artifact (or falls back to cloning + building from source). After initial setup, iterate with `augur pull` (git pull + restart) — no tagging required.

#### Step 1: Trigger the CI prebuilt artifact

On GitHub, go to **Actions > Build LibreChat > Run workflow** (or wait for the weekly Monday build). This:
- Clones `danny-avila/LibreChat` (main branch)
- Runs `npm ci` + `npm run frontend` in CI (not on your Uberspace)
- Publishes `librechat-build.tar.gz` to the `librechat-build` release

This saves your Uberspace ~10 min build time and ~2 GB RAM. The artifact stays current via weekly scheduled rebuilds.

#### Step 2: SSH into Uberspace

```bash
ssh augur@augur.uber.space
```

#### Step 3: Run the installer

```bash
curl -sL "https://raw.githubusercontent.com/ManuelKugelmann/Augur/main/augur-uberspace/install.sh?$(date +%s)" | bash
```

What happens:
1. Sets Node.js 22
2. Clones `Augur` repo to `~/augur/`
3. Creates Python venv, installs `fastmcp`, `httpx`, `pymongo`, `python-dotenv`
4. Generates `~/augur/.env` from template
5. Registers services (`trading`, `charts`) — systemd on U8, supervisord on U7
6. Downloads `librechat-build.tar.gz` from the CI prebuilt release (or latest tagged release bundle)
7. If no CI build exists: clones `danny-avila/LibreChat` and builds locally (~10 min, needs ~2 GB RAM)
8. Runs `setup.sh` — atomic swap into `~/LibreChat/`, generates `.env` with crypto keys
9. Registers LibreChat service, sets up web backend on port 3080
10. Installs `augur` CLI to `~/bin/augur`

#### Step 4: Configure environment

```bash
# Signals stack — one shared MongoDB Atlas cluster, database: signals
augur conf
# Set: MONGO_URI_SIGNALS=mongodb+srv://user:pass@cluster0.xxxxx.mongodb.net/signals

# LibreChat — same cluster, database: LibreChat
augur env
# Set: MONGO_URI=mongodb+srv://user:pass@cluster0.xxxxx.mongodb.net/LibreChat
# Set at least one LLM key:
#   OPENROUTER_API_KEY=sk-or-...
#   ANTHROPIC_API_KEY=sk-ant-...
#   OPENAI_API_KEY=sk-...
```

Crypto secrets (`CREDS_KEY`, `CREDS_IV`, `JWT_SECRET`, `JWT_REFRESH_SECRET`) are auto-generated.

#### Step 5: Verify MCP paths

```bash
augur yaml
# All __HOME__ placeholders should be replaced with /home/augur
# Verify paths like /home/augur/augur/src/store/server.py exist
```

#### Step 6: Start

```bash
augur restart
augur s    # should show RUNNING + version like "dev-a1b2c3d"
```

#### Step 7: Access

```
https://augur.uber.space
```

Register first account (becomes admin). Then lock registration:
```bash
augur env   # add: ALLOW_REGISTRATION=false
augur r     # restart
```

#### Step 8: Iterate with git pull

After pushing changes to `main` on your dev machine:
```bash
augur pull    # git pull ~/augur + restart LibreChat
```

This pulls the latest signals stack code (servers, profiles, config) and restarts. No tagging, no CI, no release — just push and pull.

To update LibreChat itself (new upstream version), re-run:
```bash
augur install dev    # re-downloads CI build or rebuilds from source
```

---

### Release Mode Walkthrough (production)

For stable deployments using tagged releases.

#### One-liner install

```bash
ssh augur@augur.uber.space
curl -sL "https://raw.githubusercontent.com/ManuelKugelmann/Augur/main/augur-uberspace/install.sh?$(date +%s)" | bash
```

Requires a tagged release to exist first. On your dev machine:
```bash
git tag v0.1.0 && git push --tags
# Wait for CI to build librechat-bundle.tar.gz and attach to release
```

#### Configure

```bash
augur conf   # signals stack: set MONGO_URI_SIGNALS
augur env    # LibreChat: set MONGO_URI + LLM key
```

#### Start

```bash
augur restart
augur s
```

#### Update

```bash
# Dev machine: tag new release
git tag v0.2.0 && git push --tags

# Uberspace: download and install
augur u
```

#### Rollback

```bash
augur rb    # restores ~/LibreChat.prev from last update
```

---

## Configuration Reference

All deployment settings live in `deploy.conf` (sourced by all scripts):

| Variable | Default | Purpose |
|----------|---------|---------|
| `UBER_USER` | `augur` | Uberspace username |
| `UBER_HOST` | `augur.uber.space` | Uberspace hostname |
| `GH_USER` | `ManuelKugelmann` | GitHub username |
| `GH_REPO` | `Augur` | Signals stack repo |
| `STACK_DIR` | `$HOME/augur` | Signals stack path |
| `APP_DIR` | `$HOME/LibreChat` | LibreChat path |
| `BACKUP_DIR` | `$HOME/backups/mongo` | Rolling MongoDB backups |
| `LC_PORT` | `3080` | LibreChat port |
| `NODE_VERSION` | `22` | Node.js version |
| `PYTHON_VERSION` | *(auto-detected)* | Python version (scans 3.13-3.10) |
| `RELEASE_TAG` | *(empty = latest)* | Pin to specific release tag |

Override any value via environment: `UBER_USER=other augur install`

---

## Day-to-Day Operations

```bash
augur help          # all commands
augur s|status      # service status + version
augur l|logs        # tail logs
augur r|restart     # restart LibreChat + trading
augur testrun       # run LibreChat in foreground (see errors directly)
augur v|version     # show version
augur u|update      # update from latest GitHub release
augur pull          # quick update via git pull (dev)
augur rb|rollback   # rollback to previous version
augur backup        # backup MongoDB to ~/backups/mongo/
augur restore [f]   # restore MongoDB from backup
augur backups       # list available backups
augur check         # health check (services, config, connectivity)
augur check -t      # health check + run test suite
augur bootstrap     # bootstrap profile data via agent
augur agents        # seed multi-agent architecture
augur proxy ...     # CLIProxyAPI management
augur env           # edit LibreChat .env
augur yaml          # edit librechat.yaml
augur conf          # edit deploy.conf
```

### Updates

```bash
# Production: tag > CI builds bundle > deploy
git tag v0.2.0 && git push --tags   # from dev
augur u                                  # on Uberspace

# Dev: push to main > quick pull
git push                              # from dev
augur pull                               # on Uberspace
```

### Rollback

```bash
augur rb    # restores ~/LibreChat.prev
```

---

## Troubleshooting

### LibreChat won't start
```bash
augur logs
# Common: wrong MONGO_URI, missing LLM key, port conflict
```

### Out of memory (Uberspace)
```bash
dmesg | tail -20
# LibreChat is configured with --max-old-space-size=1024
# If still dying: reduce to 768, or run fewer domain servers
```

### MongoDB connection fails
```bash
# Test from Uberspace
python3 -c "from pymongo import MongoClient; MongoClient('YOUR_URI').server_info(); print('ok')"
# Check: Atlas Network Access allows 0.0.0.0/0
```

### MCP server not finding API keys
When launched by LibreChat, servers inherit env from `librechat.yaml` `env:` blocks, not from `.env`. Verify the key is in both places:
```bash
grep FRED_API_KEY ~/augur/.env
grep FRED_API_KEY ~/LibreChat/librechat.yaml
```

### Port conflict
```bash
lsof -i :3080
uberspace web backend set / --http --port 3080
```

---

## Resource Limits (Uberspace)

| Resource | Limit | Usage |
|----------|-------|-------|
| RAM | 1.5 GB hard kill | ~500-800 MB (LibreChat) + ~80 MB (1 Python MCP) |
| Storage | 10 GB (expandable) | ~2 GB installed |
| Node.js | 18, 20, 22 | Requires >=20 |
| Docker | Not available | Not needed |

Signals store + all 12 domain servers run in a single combined process (`trading`, ~80 MB) via FastMCP `mount()`, well within RAM limits.

## Cost

| Service | Cost |
|---------|------|
| Uberspace | ~5 EUR/mo (pay what you want, min 1 EUR) |
| MongoDB Atlas M0 | Free (512 MB) |
| GitHub | Free |
| Cloud LLMs | Per-use (your API keys) |
| **Total** | **~5 EUR/mo + LLM usage** |
