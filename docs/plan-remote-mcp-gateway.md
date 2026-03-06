# Plan: Remote MCP Gateway for Uberspace

**Goal**: Let Claude.ai and Claude Code (web) directly manage the TradingAssistant deployment on `assist.uber.space` via a remote MCP server with OAuth authentication.

---

## Problem

Currently, operating the Uberspace server requires SSH access. Claude Code (local CLI) can SSH in, but Claude.ai and Claude Code web cannot. A remote MCP server exposed over HTTPS with OAuth would let any Claude client manage the server directly — check status, view logs, restart services, deploy updates, run diagnostics, query data.

---

## Architecture Decision: Python FastMCP (not TypeScript)

**Recommendation: Stay with Python FastMCP.**

Rationale:
- The entire stack is already Python FastMCP. Adding a TypeScript server creates a second runtime, second dependency tree, second build step.
- **Python FastMCP v2.11+** has full OAuth support: `RemoteAuthProvider` (for OIDC/DCR-capable providers) and `OAuthProxy` (for GitHub/Google that lack DCR). Both are production-ready.
- Uberspace already has the Python venv set up. Node.js is only used for LibreChat itself.
- The gateway server needs to call `supervisorctl`, read logs, run `ta` commands — all trivial in Python via `subprocess`. No TypeScript advantage here.
- If OAuth proves difficult in Python FastMCP, TypeScript remains a fallback, but the Python path is shorter.

---

## Architecture

```
Claude.ai / Claude Code (web)
    │
    │  HTTPS + OAuth 2.1 Bearer Token
    │  Streamable HTTP transport
    ▼
https://mcp.assist.uber.space/mcp   ← new subdomain
    │
    │  Uberspace reverse proxy (auto TLS)
    ▼
localhost:8070                        ← gateway MCP server (Python FastMCP)
    │
    ├─ subprocess: supervisorctl      ← service management
    ├─ subprocess: ta <cmd>           ← ops CLI
    ├─ subprocess: git                ← repo operations
    ├─ file reads: ~/logs/*           ← log access
    ├─ file reads: ~/mcps/profiles/*  ← profile browsing
    └─ httpx: localhost:3080          ← LibreChat health check
```

---

## OAuth Strategy

### Option A: GitHub OAuth via OAuthProxy (recommended)

Use Python FastMCP's `OAuthProxy` to authenticate via GitHub. GitHub doesn't support DCR (RFC 7591), so OAuthProxy acts as intermediary — it handles Dynamic Client Registration emulation for Claude.ai's DCR-based flow.

```python
from fastmcp import FastMCP
from fastmcp.server.auth import OAuthProxy

auth = OAuthProxy(
    # GitHub OAuth App credentials
    client_id=os.environ["GH_OAUTH_CLIENT_ID"],
    client_secret=os.environ["GH_OAUTH_CLIENT_SECRET"],
    authorize_url="https://github.com/login/oauth/authorize",
    token_url="https://github.com/login/oauth/access_token",
    # Restrict to repo owner
    allowed_users=["ManuelKugelmann"],
    base_url="https://mcp.assist.uber.space",
)

mcp = FastMCP("TradingAssistant Gateway", auth=auth)
```

**Setup**: Create a GitHub OAuth App at github.com/settings/developers. Set callback URL to `https://claude.ai/api/mcp/auth_callback`.

### Option B: Simple Bearer Token (simpler, less standard)

Skip OAuth entirely. Use a static API key validated in middleware. Claude Code supports `--header "Authorization: Bearer $TOKEN"` for remote servers. However, Claude.ai's connector UI expects OAuth — so this only works for Claude Code, not Claude.ai.

### Option C: Self-hosted OIDC (overkill)

Run a minimal OIDC provider. Not worth the complexity for a single-user system.

**Verdict**: Option A. GitHub OAuth via OAuthProxy is the right balance — works with both Claude.ai and Claude Code, leverages existing GitHub identity, single-user allowlist is trivial.

---

## Tools to Expose

### Tier 1 — Server Operations (core value)

| Tool | Description | Implementation |
|------|-------------|----------------|
| `status` | Service status, version, uptime | `supervisorctl status` + parse |
| `restart(service?)` | Restart LibreChat or specific MCP | `supervisorctl restart <svc>` |
| `logs(service, lines?)` | Tail recent logs | Read `~/logs/<svc>.out.log` |
| `deploy_update` | Pull latest release | `ta u` (with confirmation token) |
| `deploy_pull` | Quick dev update from git | `ta pull` |
| `deploy_rollback` | Rollback to previous version | `ta rb` |
| `version` | Current deployed version | Read `~/LibreChat/.version` |

### Tier 2 — Diagnostics

| Tool | Description | Implementation |
|------|-------------|----------------|
| `disk_usage` | Disk space summary | `df -h` + `du -sh` key dirs |
| `memory_usage` | RAM per service | `ps aux` filtered to our processes |
| `health_check` | End-to-end system health | Check supervisord, MongoDB ping, LibreChat HTTP |
| `cron_status` | Last data sync, next scheduled | Parse cron log + `ta sync` timestamp |
| `error_scan(hours?)` | Grep recent logs for errors | `grep -i error ~/logs/*.log` |

### Tier 3 — Data & Profile Operations

| Tool | Description | Implementation |
|------|-------------|----------------|
| `list_profiles(kind?, region?)` | Browse profile inventory | Read INDEX files |
| `get_profile(kind, id)` | Read a profile | Read JSON file |
| `data_sync` | Force git push of data repo | `ta sync` |
| `db_stats` | MongoDB collection stats | pymongo `collStats` |

### Tier 4 — Configuration (guarded)

| Tool | Description | Implementation |
|------|-------------|----------------|
| `get_config(file)` | Read config file (redacted secrets) | Read + mask env values |
| `set_env(key, value)` | Update .env variable | sed in-place + restart |

### Out of Scope (too dangerous for remote)

- Arbitrary shell execution
- File deletion
- SSH key management
- User/permission management
- Direct MongoDB writes (use signals-store MCP for that)

---

## Security Model

1. **Authentication**: GitHub OAuth via OAuthProxy → only `ManuelKugelmann` allowed
2. **Authorization**: All tools available to authenticated user (single-user system)
3. **Dangerous ops**: `deploy_update`, `deploy_rollback`, `set_env` require a confirmation flow — the tool returns a confirmation token, caller must pass it back to confirm
4. **Secret redaction**: `get_config` masks values for keys matching `*SECRET*`, `*KEY*`, `*PASSWORD*`, `*URI*`
5. **Rate limiting**: Optional, via FastMCP middleware — 60 requests/minute
6. **Origin validation**: FastMCP validates `Origin` header per MCP spec
7. **HTTPS only**: Uberspace auto-TLS via Let's Encrypt
8. **Audit log**: All tool calls logged to `~/logs/mcp-gateway.audit.log` with timestamp, tool, args, result summary

---

## File Layout (in repo)

```
src/gateway/
├── server.py          ← main FastMCP server with all tools
├── auth.py            ← OAuthProxy configuration
├── tools/
│   ├── ops.py         ← status, restart, logs, version
│   ├── deploy.py      ← deploy_update, deploy_pull, deploy_rollback
│   ├── diagnostics.py ← disk, memory, health, cron, errors
│   ├── data.py        ← profiles, sync, db_stats
│   └── config.py      ← get_config, set_env
└── security.py        ← confirmation tokens, secret redaction, audit
```

---

## Deployment on Uberspace

### 1. Subdomain Setup

```bash
uberspace web domain add mcp.assist.uber.space
```

### 2. Supervisord Service

```ini
# ~/etc/services.d/mcp-gateway.ini
[program:mcp-gateway]
directory=%(ENV_HOME)s/mcps
command=%(ENV_HOME)s/mcps/venv/bin/python src/gateway/server.py
environment=PORT=8070
autostart=true
autorestart=true
stderr_logfile=%(ENV_HOME)s/logs/mcp-gateway.err.log
stdout_logfile=%(ENV_HOME)s/logs/mcp-gateway.out.log
```

### 3. Reverse Proxy

```bash
uberspace web backend set mcp.assist.uber.space --http --port 8070
```

### 4. Environment Variables (add to ~/mcps/.env)

```bash
# Gateway OAuth (GitHub OAuth App)
GH_OAUTH_CLIENT_ID=...
GH_OAUTH_CLIENT_SECRET=...
GATEWAY_ALLOWED_USERS=ManuelKugelmann
GATEWAY_PORT=8070
GATEWAY_BASE_URL=https://mcp.assist.uber.space
```

### 5. Register in Claude.ai

Settings → Connectors → Add custom connector:
- URL: `https://mcp.assist.uber.space/mcp`
- OAuth completes automatically via GitHub login

### 6. Register in Claude Code

```bash
claude mcp add trading-gateway --transport http https://mcp.assist.uber.space/mcp
claude mcp auth trading-gateway  # triggers OAuth flow
```

---

## Integration with Existing Deploy Pipeline

### Changes to TradeAssistant.sh

Add gateway service registration to `install` phase:

```bash
# In the service registration loop, add:
write_ini "mcp-gateway" "${STACK}/venv/bin/python src/gateway/server.py" true
uberspace web domain add mcp.${UBER_HOST} 2>/dev/null || true
uberspace web backend set mcp.${UBER_HOST} --http --port 8070
```

Add `ta gateway` command:

```bash
gateway)  supervisorctl restart mcp-gateway ;;
```

### Changes to deploy.conf

```bash
GATEWAY_PORT=8070
```

### Changes to librechat.yaml

Not needed — this MCP is accessed remotely by Claude.ai, not by the local LibreChat instance. However, you could optionally add it as a local MCP too for the LibreChat UI.

### Python Dependencies (add to requirements.txt)

```
# No new deps — FastMCP already handles Streamable HTTP and OAuth
# OAuthProxy is built into fastmcp>=2.11
```

Verify that `fastmcp>=2.11` is available. Current requirement is `fastmcp>=2.0` — bump to `fastmcp>=2.11`.

### CI Release (release.yml)

No changes needed — `src/gateway/` is part of the repo, deployed via `ta pull` or release bundle.

---

## Implementation Phases

### Phase 1: Minimal Viable Gateway
- `server.py` with `status`, `logs`, `version`, `restart` tools
- No OAuth yet — test with `--header` bearer token locally
- Deploy to Uberspace, verify Streamable HTTP works through reverse proxy
- **Estimate: ~200 lines of Python**

### Phase 2: OAuth
- Add OAuthProxy with GitHub credentials
- Test with Claude Code (`claude mcp add` + `claude mcp auth`)
- Test with Claude.ai connector
- **Estimate: ~50 lines of Python (auth.py)**

### Phase 3: Full Tool Suite
- Add deploy, diagnostics, data, config tools
- Add confirmation flow for dangerous ops
- Add audit logging
- **Estimate: ~400 lines of Python**

### Phase 4: Polish
- Error handling, timeouts, graceful degradation
- Integration into `ta install` flow
- Update docs and README

---

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| OAuthProxy not mature in Python FastMCP | Fall back to TypeScript FastMCP or manual OAuth endpoints |
| Uberspace blocks subdomain for MCP | Use path-based routing: `assist.uber.space/mcp-gateway/` |
| RAM pressure (one more Python process) | Gateway is lightweight (~30MB). Can stop unused domain servers |
| Claude.ai DCR compatibility issues | Support manual client ID/secret as backup |
| Security: remote server management | GitHub allowlist + confirmation tokens + audit log + no arbitrary exec |
| FastMCP Streamable HTTP bugs | SSE transport as fallback (also supported by Claude.ai) |

---

## Open Questions

1. **Subdomain vs path routing?** Subdomain (`mcp.assist.uber.space`) is cleaner but requires DNS setup. Path (`assist.uber.space/mcp-gateway`) works immediately. Start with path, migrate to subdomain later?

2. **Should LibreChat also connect to this gateway?** It could, giving the LibreChat-hosted Claude the same ops tools. But that creates a circular dependency (gateway restarts LibreChat, which connects to gateway). Probably not worth it.

3. **Multiple gateway instances?** One gateway that proxies to all 12 domain servers, or expose each domain server individually? One gateway is simpler and more secure — it's the ops layer, not a data layer. Domain data stays accessed via LibreChat's local MCPs.

4. **Token storage for Claude Code web?** Claude Code web stores OAuth tokens in the browser session. If the session expires, re-auth is needed. Not a big deal for single-user.
