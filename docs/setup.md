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

#### Step 1: Clone the repo

```bash
git clone https://github.com/ManuelKugelmann/Augur.git
```

#### Step 2: Enter the project directory

```bash
cd Augur
```

#### Step 3: Create a Python virtual environment

```bash
python3 -m venv venv
```

#### Step 4: Activate the virtual environment

```bash
source venv/bin/activate
```

#### Step 5: Install dependencies

```bash
pip install -r requirements.txt
```

#### Step 6: Create your `.env` file from the template

```bash
cp .env.example .env
```

#### Step 7: Edit `.env` — set at minimum `MONGO_URI_SIGNALS`

```bash
nano .env
```

#### Step 8: Start the combined server (all tools: store + 12 domains)

```bash
python src/servers/combined_server.py
```

Run individual servers standalone for testing:

```bash
python src/store/server.py
```

```bash
python src/servers/weather_server.py
```

```bash
python src/servers/macro_server.py
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
5. Registers systemd services (`trading`, `charts`)
6. Downloads `librechat-build.tar.gz` from the CI prebuilt release (or latest tagged release bundle)
7. If no CI build exists: clones `danny-avila/LibreChat` and builds locally (~10 min, needs ~2 GB RAM)
8. Runs `setup.sh` — atomic swap into `~/LibreChat/`, generates `.env` with crypto keys
9. Registers LibreChat service, sets up web backend on port 3080
10. Installs `augur` CLI to `~/bin/augur`

#### Step 4: Configure signals stack — set `MONGO_URI_SIGNALS`

```bash
augur conf
```

In the editor, add your MongoDB connection string (database: `signals`):

```
MONGO_URI_SIGNALS=mongodb+srv://user:pass@cluster0.xxxxx.mongodb.net/signals
```

#### Step 5: Configure LibreChat — set `MONGO_URI` + LLM key

```bash
augur env
```

In the editor, set these values (same Atlas cluster, database: `LibreChat`):

```
MONGO_URI=mongodb+srv://user:pass@cluster0.xxxxx.mongodb.net/LibreChat
OPENROUTER_API_KEY=sk-or-...
```

Or use `ANTHROPIC_API_KEY=sk-ant-...` or `OPENAI_API_KEY=sk-...` instead.

Crypto secrets (`CREDS_KEY`, `CREDS_IV`, `JWT_SECRET`, `JWT_REFRESH_SECRET`) are auto-generated.

#### Step 6: Verify MCP paths in `librechat.yaml`

```bash
augur yaml
```

All `__HOME__` placeholders should already be replaced with `/home/augur`. Verify paths like `/home/augur/augur/src/store/server.py` exist.

#### Step 7: Start all services

```bash
augur restart
```

#### Step 8: Verify services are running

```bash
augur s
```

Should show RUNNING + version like `dev-a1b2c3d`.

#### Step 9: Access the web UI

Open in your browser:

```
https://augur.uber.space
```

Register the first account (becomes admin).

#### Step 10: Lock registration

```bash
augur env
```

Add this line: `ALLOW_REGISTRATION=false`, then restart:

```bash
augur r
```

#### Step 11: Iterate with git pull (ongoing development)

After pushing changes to `main` on your dev machine:

```bash
augur pull
```

This pulls the latest signals stack code and restarts. No tagging, no CI, no release — just push and pull.

#### Step 12: Update LibreChat itself (when upstream changes)

```bash
augur install dev
```

---

### Release Mode Walkthrough (production)

For stable deployments using tagged releases.

#### Step 1: Create a tagged release (on your dev machine)

```bash
git tag v0.1.0
```

```bash
git push --tags
```

Wait for CI to build `librechat-bundle.tar.gz` and attach it to the release.

#### Step 2: SSH into Uberspace

```bash
ssh augur@augur.uber.space
```

#### Step 3: Run the installer

```bash
curl -sL "https://raw.githubusercontent.com/ManuelKugelmann/Augur/main/augur-uberspace/install.sh?$(date +%s)" | bash
```

#### Step 4: Configure signals stack

```bash
augur conf
```

Set `MONGO_URI_SIGNALS` in the editor.

#### Step 5: Configure LibreChat

```bash
augur env
```

Set `MONGO_URI` + at least one LLM API key in the editor.

#### Step 6: Start all services

```bash
augur restart
```

#### Step 7: Verify

```bash
augur s
```

#### Update to a new release

On your dev machine:

```bash
git tag v0.2.0
```

```bash
git push --tags
```

On Uberspace:

```bash
augur u
```

#### Rollback

```bash
augur rb
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
| `NODE_VERSION` | `24` | Node.js version |
| `PYTHON_VERSION` | *(auto-detected)* | Python version (scans 3.13-3.10) |
| `RELEASE_TAG` | *(empty = latest)* | Pin to specific release tag |

Override any value via environment: `UBER_USER=other augur install`

---

## Day-to-Day Operations

```bash
augur help          # all commands
augur status        # service status + version
augur logs          # tail logs
augur restart       # restart LibreChat + trading
augur testrun       # run LibreChat in foreground (see errors directly)
augur debugstart    # full diagnostics + foreground run
augur version       # show version
augur pull          # quick git-pull update (dev)
augur update        # update stack (git pull + deps + LibreChat release)
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

On your dev machine, push changes:

```bash
git push
```

On Uberspace, update everything (git pull + deps + LibreChat release):

```bash
augur u
```

---

## Troubleshooting

### LibreChat won't start

Check the logs for errors:

```bash
augur logs
```

Common causes: wrong `MONGO_URI`, missing LLM key, port conflict.

### Out of memory (Uberspace)

Check the kernel log:

```bash
dmesg | tail -20
```

LibreChat is configured with `--max-old-space-size=1024`. If still dying, reduce to 768 or run fewer domain servers.

### MongoDB connection fails

Test the connection from Uberspace:

```bash
python3 -c "from pymongo import MongoClient; MongoClient('YOUR_URI').server_info(); print('ok')"
```

Check that Atlas Network Access allows `0.0.0.0/0`.

### MCP server not finding API keys

When launched by LibreChat, servers inherit env from `librechat.yaml` `env:` blocks, not from `.env`. Verify the key is in both places:

```bash
grep FRED_API_KEY ~/augur/.env
```

```bash
grep FRED_API_KEY ~/LibreChat/librechat.yaml
```

### Port conflict

Check what is using port 3080:

```bash
lsof -i :3080
```

Re-register the web backend:

```bash
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
