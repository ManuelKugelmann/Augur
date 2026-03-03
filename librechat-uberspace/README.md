# LibreChat Lite → Uberspace

Minimal LibreChat deployment: cloud LLMs, MongoDB Atlas, MCP servers (filesystem + memory + sqlite), git-versioned data storage. No Docker, no Meilisearch, no RAG, no Redis.

## Architecture

```
┌──────────────┐     ┌────────┐     ┌───────────┐     ┌──────────────────────────┐
│ Codespace/WSL│────▶│ GitHub │────▶│ CI Release │────▶│ Uberspace              │
│ dev + test   │push │  repo  │tag  │ build+tar  │pull │                        │
└──────────────┘     └────────┘     └───────────┘     │ LibreChat (:3080)      │
                                                       │ ├─ MCP: filesystem     │
                                                       │ ├─ MCP: memory (JSON)  │
                                                       │ └─ MCP: sqlite         │
                                                       │                        │
                                                       │ git-sync cron ──push──▶│ GitHub (private)
                                                       └────────────────────────┘ data repo
                                                              │
                                              ┌───────────────┼──────────┐
                                              ▼               ▼          ▼
                                       MongoDB Atlas    Cloud LLMs    FS data
                                       (free tier)      (APIs)        (git versioned)
```

## Prerequisites

- GitHub account (fork this repo)
- MongoDB Atlas account (free tier) — https://cloud.mongodb.com
- API keys for LLM providers (Anthropic, OpenAI, etc.)
- Uberspace account — https://uberspace.de

## Quick Start

### 1. Fork & configure GitHub repo

```bash
# Fork on GitHub, then clone
git clone git@github.com:YOUR_USER/librechat-uberspace.git
cd librechat-uberspace
```

Add GitHub repo secrets (Settings → Secrets → Actions):
- `UBERSPACE_HOST` — `yourname.uber.space`
- `UBERSPACE_USER` — your username
- `UBERSPACE_SSH_KEY` — private key for SSH access

For private repos, also add:
- `GH_DEPLOY_TOKEN` — GitHub PAT with `repo` scope

### 2. Create MongoDB Atlas cluster

1. https://cloud.mongodb.com → New Project → Build Database → Shared (free)
2. Create database user + password
3. Network Access → Allow `0.0.0.0/0` (Uberspace has no static IP)
4. Connect → copy connection string

### 3. First deploy to Uberspace

```bash
# SSH in
ssh YOUR_USER@YOUR_HOST.uber.space

# Set Node 22
uberspace tools version use node 22

# Install (one-liner)
curl -sL https://github.com/YOUR_USER/librechat-uberspace/releases/latest/download/bootstrap.sh | bash

# Configure
nano ~/LibreChat/.env
# Set: MONGO_URI, CREDS_KEY, CREDS_IV, API keys
# See config/.env.uberspace for reference

# Start
supervisorctl start librechat
```

### 4. Access

```
https://YOUR_USER.uber.space
```

## Updates

Same one-liner — detects existing install, preserves `.env` + data:
```bash
curl -sL https://github.com/YOUR_USER/librechat-uberspace/releases/latest/download/bootstrap.sh | bash
```

## Release workflow

```bash
# Tag → CI builds → release published
git tag v0.2.0 && git push --tags

# Then on Uberspace:
lc u   # shortcut for update
```

## MCP Servers

Configured in `config/librechat.yaml`. Included out of the box:

| MCP Server | Purpose | Storage |
|---|---|---|
| `@modelcontextprotocol/server-filesystem` | File read/write | `~/librechat-data/files/` |
| `@modelcontextprotocol/server-memory` | Knowledge graph (entities + relations) | `~/librechat-data/memory.json` |
| `mcp-sqlite` | Structured data (logs, research, notes) | `~/librechat-data/data.db` |

All data lives under `~/librechat-data/` which is a **git repo synced to GitHub** every 15 minutes.

## Git-versioned data

The `~/librechat-data/` directory is a separate private GitHub repo:
- Full version history of memory, files, SQLite DB
- Survives host migration
- Clone to new host instantly
- `git log` shows what changed when

Setup: see `scripts/setup-data-repo.sh`

## Ops shortcuts

After install, `lc` command is available:
```bash
lc s          # status
lc l          # tail logs  
lc r          # restart
lc v          # show version
lc u          # update (pull latest release)
lc rb         # rollback to previous version
lc sync       # force git sync of data
```

## Rollback

```bash
lc rb
# or manually:
supervisorctl stop librechat
rm -rf ~/LibreChat && mv ~/LibreChat.prev ~/LibreChat
supervisorctl start librechat
```

## Sync with upstream LibreChat

```bash
git remote add upstream https://github.com/danny-avila/LibreChat.git
git fetch upstream
git merge upstream/main
git push && git tag v0.X.0 && git push --tags
```

## Resource limits (Uberspace)

| Resource | Limit | LibreChat usage |
|---|---|---|
| RAM | 1.5 GB hard kill | ~500-800 MB runtime |
| Storage | 10 GB (up to 100 GB) | ~2 GB installed |
| Node.js | 18, 20, 22 | Requires ≥20.19.0 |
| Docker | ❌ | Not needed (npm install) |

## Cost

| Service | Cost |
|---|---|
| Uberspace | ~5€/mo (pay what you want) |
| MongoDB Atlas | Free (shared tier) |
| Cloud LLMs | Per-use (your API keys) |
| GitHub | Free (private repos) |
| **Total** | **~5€/mo + LLM usage** |
