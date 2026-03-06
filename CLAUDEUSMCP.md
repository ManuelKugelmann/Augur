# CLAUDEUSMCP.md — Dev Workflow: Remote MCP Gateway on Uberspace

**This is a dev/ops workflow tool, NOT part of the production TradingAssistant stack.**

It deploys a lightweight MCP gateway on Uberspace so that Claude.ai (web + mobile)
and Claude Code can manage the server remotely. Think of it as SSH-over-MCP for our
dev workflow.

**Supported clients**: Claude.ai web, Claude iOS/Android, Claude Code CLI, Claude Desktop.

---

## Architecture

The gateway wraps `claude mcp serve` (Claude Code's built-in MCP server mode) behind
a FastMCP HTTP proxy with GitHub OAuth. Claude.ai gets direct access to Bash, Read,
Write, Edit, Grep, and all Claude Code tools — running natively on the Uberspace server.

**No custom Python tools needed.** Claude.ai can run `supervisorctl status`, `ta pull`,
read logs, edit configs — everything through Claude Code's native tools.

```
Claude.ai (web/mobile) / Claude Code CLI / Claude Desktop
    |
    |  1. Discovers OAuth via /.well-known/oauth-protected-resource
    |  2. Registers via DCR (/register) — gets back our GitHub app creds
    |  3. OAuth flow: user → our /authorize → GitHub login → our /auth/callback → client callback
    |  4. Streamable HTTP transport with JWT bearer token
    v
https://mcp.assist.uber.space/mcp
    |
    |  Uberspace nginx (auto TLS via Let's Encrypt)
    v
localhost:8070  (FastMCP HTTP proxy — ~60 lines of Python)
    |
    |  stdio subprocess via create_proxy({mcpServers: ...})
    v
claude mcp serve  (Claude Code as MCP server)
    |
    +-- Bash          (shell commands: supervisorctl, ta, git, ...)
    +-- Read/Write    (file access: logs, profiles, configs, ...)
    +-- Edit          (in-place file editing)
    +-- GrepTool      (search across codebase)
    +-- GlobTool      (find files by pattern)
    +-- LS            (directory listing)
    +-- WebFetch      (fetch URLs)
    +-- Agent         (sub-agents for complex tasks)
```

### How `claude mcp serve` works

- Exposes Claude Code's **native tools only** as MCP tools over stdio
- Tools are direct execution — **no LLM calls**, no Anthropic API key required
- Bash runs bash, Read reads files, Write writes files — zero overhead
- Claude.ai provides all the reasoning; the server just executes
- Does NOT proxy other configured MCP servers (only built-in tools)

### What this replaces

Previous plan had ~800 lines of custom Python tools. All unnecessary —
Claude Code's native tools cover every use case.

---

## Auth: Unattended Headless Mode

`claude mcp serve` runs headless — it needs a persistent auth token, not a
browser-based OAuth session.

### Auth Options

| Method | TTL | Headless | Billing |
|--------|-----|----------|---------|
| `claude login` (browser) | ~8-12 h | No | Subscription |
| Copy `credentials.json` | ~6 h | Refresh bug | Subscription |
| `claude setup-token` | 1 year | Yes | Subscription |
| `ANTHROPIC_API_KEY` | Unlimited | Yes | Pay-per-token |

**Use `setup-token`.** Avoids all known refresh bugs and race conditions.

### Known Auth Bugs (avoided by setup-token)

| Bug | Status |
|-----|--------|
| `-p` headless mode doesn't refresh short-lived tokens -> 401 after ~15 min | open |
| Concurrent sessions cause refresh token race condition | open |
| Copying `credentials.json` to remote ignores `refreshToken` | open |

### Setup (one-time, on a machine with a browser)

```bash
claude setup-token   # -> sk-ant-oat01-...   <- shown once, save it immediately
```

**Never set both `CLAUDE_CODE_OAUTH_TOKEN` and `ANTHROPIC_API_KEY`** — auth conflict.

### Onboarding Bypass (headless machines)

Write `~/.claude.json` to skip the interactive wizard:

```json
{
  "hasCompletedOnboarding": true,
  "lastOnboardingVersion": "2.1.29",
  "oauthAccount": {
    "accountUuid": "...",
    "emailAddress": "...",
    "organizationUuid": "..."
  }
}
```

Get values from `cat ~/.claude.json` after initial local login.

---

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| Uberspace account | `assist.uber.space` |
| Node.js 22+ | For Claude Code CLI (already on Uberspace) |
| Python 3.9+ | For FastMCP proxy (already on Uberspace) |
| Claude Code CLI | `npm install -g @anthropic-ai/claude-code` |
| `fastmcp>=3.0` | For OAuth + proxy + config dict transport |
| GitHub OAuth App | Created in Step 1 (free) |

**Not needed**: Anthropic API key (serve mode exposes tools directly, no LLM calls),
custom Python tools, `--dangerously-skip-permissions` (the MCP client is responsible
for implementing user confirmation for individual tool calls).

---

## Step 1: Create GitHub OAuth App

1. Go to https://github.com/settings/developers -> **New OAuth App**
2. Fill in:
   - **Application name**: `TradingAssistant MCP Gateway`
   - **Homepage URL**: `https://mcp.assist.uber.space`
   - **Authorization callback URL**: `https://mcp.assist.uber.space/auth/callback`
3. Click **Register application**
4. Copy the **Client ID**
5. Click **Generate a new client secret**, copy it
6. Save both for Step 6

> **Important**: The callback URL points to **our server**, NOT to Claude.ai.
> FastMCP's OAuthProxy handles the full redirect chain:
>
> 1. Claude.ai registers via DCR -> gets our GitHub app credentials
> 2. User clicks Connect -> redirected to our `/authorize` endpoint
> 3. We redirect to GitHub login (callback = our `/auth/callback`)
> 4. GitHub redirects back to us with auth code
> 5. We exchange code for token, mint a FastMCP JWT
> 6. We redirect to Claude.ai's callback with our JWT
>
> This means all MCP clients (Claude.ai web, mobile, CLI, Desktop) work
> through the same OAuth App — no per-client callback URLs needed.

---

## Step 2: Set Up Subdomain on Uberspace

`.uber.space` subdomains: DNS resolves automatically (Uberspace manages the zone),
but each subdomain must be [registered individually](https://manual.uberspace.de/en/web-domains.html)
— no wildcard domains (Let's Encrypt HTTP validation limitation):

```bash
uberspace web domain add mcp.assist.uber.space
```

That's it — no A/AAAA records to configure at a registrar.
TLS certificate is provisioned automatically via Let's Encrypt.

---

## Step 3: Install Claude Code CLI + Auth Token

```bash
npm install -g @anthropic-ai/claude-code
claude --version
```

### Verify serve mode works

```bash
# Verify with auth token (must work without ANTHROPIC_API_KEY)
echo '{"jsonrpc":"2.0","method":"initialize","id":1,"params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' \
  | CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-... claude mcp serve
# Expected: JSON with server capabilities and tool list
```

Verify this works **before** continuing. If `claude mcp serve` fails without
`ANTHROPIC_API_KEY`, the gateway won't start.

---

## Step 4: Install Python Dependencies

```bash
cd ~/mcps
python3 -m venv venv 2>/dev/null || true
venv/bin/pip install -U 'fastmcp>=3.0' httpx python-dotenv
```

---

## Step 5: Create the Gateway

### `src/gateway/server.py`

```python
"""MCP Gateway — wraps `claude mcp serve` with GitHub OAuth + HTTP transport.

Bridges:  claude mcp serve (stdio) -> FastMCP proxy (Streamable HTTP + OAuth)
Result:   Claude.ai gets direct Bash/Read/Write/Edit/Grep on the server.
"""
import os
import warnings

import httpx
from dotenv import load_dotenv
from fastmcp.server import create_proxy
from fastmcp.server.auth.providers.github import GitHubProvider
from fastmcp.server.auth import TokenVerifier

load_dotenv()


class GitHubUserFilter(TokenVerifier):
    """Restrict access to specific GitHub usernames."""

    def __init__(self, allowed_users: list[str]):
        super().__init__()
        self.allowed = {u.lower() for u in allowed_users}

    async def verify_token(self, token: str) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.github.com/user",
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            user = resp.json()
        if user["login"].lower() not in self.allowed:
            raise ValueError(f"User {user['login']} not in allowlist")
        return {"sub": user["login"], "name": user.get("name", "")}


def _get_auth():
    """GitHub OAuth via FastMCP's built-in GitHubProvider."""
    client_id = os.environ.get("GH_OAUTH_CLIENT_ID")
    client_secret = os.environ.get("GH_OAUTH_CLIENT_SECRET")
    if not client_id or not client_secret:
        warnings.warn("No OAuth credentials — running WITHOUT auth", stacklevel=2)
        return None

    allowed = [
        u.strip()
        for u in os.environ.get("ALLOWED_GITHUB_USERS", "").split(",")
        if u.strip()
    ]

    provider = GitHubProvider(
        client_id=client_id,
        client_secret=client_secret,
        base_url=os.environ.get(
            "GATEWAY_BASE_URL", "https://mcp.assist.uber.space"
        ),
        token_verifier=GitHubUserFilter(allowed) if allowed else None,
    )
    if not allowed:
        warnings.warn(
            "ALLOWED_GITHUB_USERS not set — any GitHub user can connect",
            stacklevel=2,
        )
    return provider


# Wrap claude mcp serve (stdio) as an HTTP proxy with OAuth.
# NOTE: create_proxy() does NOT accept plain command strings — use a config dict.
# A string like "claude mcp serve" would fail infer_transport() with ValueError.
proxy = create_proxy(
    {
        "mcpServers": {
            "claude-code": {
                "command": "claude",
                "args": ["mcp", "serve"],
                "transport": "stdio",
            }
        }
    },
    name="TradingAssistant Gateway",
    auth=_get_auth(),
)

if __name__ == "__main__":
    port = int(os.environ.get("GATEWAY_PORT", "8070"))
    proxy.run(transport="streamable-http", host="0.0.0.0", port=port)
```

### Create the files

```bash
mkdir -p ~/mcps/src/gateway
touch ~/mcps/src/gateway/__init__.py
# Copy server.py content above to ~/mcps/src/gateway/server.py
```

---

## Step 6: Configure Environment

```bash
cat >> ~/mcps/.env << 'EOF'

# -- MCP Gateway -----------------------------------------------
GH_OAUTH_CLIENT_ID=Iv1.xxxxxxxxxxxxxxxx
GH_OAUTH_CLIENT_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
GATEWAY_PORT=8070
GATEWAY_BASE_URL=https://mcp.assist.uber.space
ALLOWED_GITHUB_USERS=ManuelKugelmann

# -- Claude Code Auth ------------------------------------------
CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-...

# -- Notifications ---------------------------------------------
NOTIFY_URL=https://ntfy.sh/your-topic
EOF

chmod 600 ~/mcps/.env
```

Replace the placeholder values with real credentials from Steps 1 and 3.

---

## Step 7: Register Supervisord Service

```bash
cat > ~/etc/services.d/mcp-gateway.ini << 'EOF'
[program:mcp-gateway]
directory=%(ENV_HOME)s/mcps
command=%(ENV_HOME)s/mcps/venv/bin/python -m src.gateway.server
autostart=true
autorestart=true
environment=
    PATH="%(ENV_HOME)s/.npm-global/bin:%(ENV_PATH)s",
    CLAUDE_CODE_OAUTH_TOKEN="%(ENV_CLAUDE_CODE_OAUTH_TOKEN)s"
stderr_logfile=%(ENV_HOME)s/logs/mcp-gateway.err.log
stdout_logfile=%(ENV_HOME)s/logs/mcp-gateway.out.log
EOF

mkdir -p ~/logs
supervisorctl update      # reread + add + start in one step
supervisorctl status mcp-gateway
```

The `PATH` environment line is required — supervisord inherits a minimal PATH
that won't find `claude` in `~/.npm-global/bin`.

---

## Step 8: Set Up Reverse Proxy

Route the subdomain to the gateway port:

```bash
uberspace web backend set mcp.assist.uber.space --http --port 8070
```

Verify:

```bash
supervisorctl status mcp-gateway
curl -s -o /dev/null -w "%{http_code}" https://mcp.assist.uber.space/mcp
# Expected: 401 (OAuth required) or 405 (method not allowed for GET)
curl -s https://mcp.assist.uber.space/.well-known/oauth-protected-resource
```

---

## Step 9: Auth Monitoring Daemon

Monitors token health passively (expiry check from `credentials.json`) and
actively (live `claude -p` probe). Sends ntfy notification on any failure.

### `~/bin/claude-auth-daemon.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
source ~/mcps/.env

WARN_DAYS=${CLAUDE_WARN_DAYS:-30}
CREDS=~/.claude/.credentials.json

check_expiry() {
    [[ -f "$CREDS" ]] || return 0
    exp=$(python3 -c "import json,sys; d=json.load(open('$CREDS')); print(d.get('expiresAt',''))" 2>/dev/null) || return 0
    [[ -z "$exp" ]] && return 0
    now=$(date +%s); exp_s=$(date -d "$exp" +%s 2>/dev/null || date -j -f "%Y-%m-%dT%H:%M:%SZ" "$exp" +%s)
    days_left=$(( (exp_s - now) / 86400 ))
    if (( days_left < 0 )); then
        curl -sd "Claude token EXPIRED on $(hostname)" "$NOTIFY_URL"; exit 1
    elif (( days_left < WARN_DAYS )); then
        curl -sd "Claude token expires in ${days_left}d on $(hostname)" "$NOTIFY_URL"
    fi
}

check_live() {
    output=$(CLAUDE_CODE_OAUTH_TOKEN="$CLAUDE_CODE_OAUTH_TOKEN" claude -p "echo ok" 2>&1) || true
    if echo "$output" | grep -qiE "authentication_error|401|token has expired|unauthorized"; then
        curl -sd "Claude auth failure on $(hostname): $output" "$NOTIFY_URL"; exit 1
    fi
}

check_expiry
[[ "${1:-}" == "--once" ]] && check_live || while true; do check_live; sleep 1800; done
```

```bash
chmod +x ~/bin/claude-auth-daemon.sh
```

### Cron setup

```bash
# Check every 30 minutes
*/30 * * * *  bash -c 'source ~/mcps/.env && ~/bin/claude-auth-daemon.sh --once'

# Renewal reminder at month 11
0 9 1 */11 * curl -sd "Claude token renewal due on $(hostname)" "$NOTIFY_URL"
```

### 401 detection in automation scripts

```bash
source ~/mcps/.env
output=$(CLAUDE_CODE_OAUTH_TOKEN="$CLAUDE_CODE_OAUTH_TOKEN" claude -p "your task" 2>&1) && rc=$? || rc=$?
if echo "$output" | grep -qiE "authentication_error|401|token has expired"; then
    curl -sd "Claude reauth needed on $(hostname)" "$NOTIFY_URL"
    exit 1
fi
```

### Token renewal (once a year)

```bash
claude setup-token          # run on a machine with a browser
# Update CLAUDE_CODE_OAUTH_TOKEN in ~/mcps/.env
supervisorctl restart mcp-gateway
```

Renew ~1 month before expiry. The cron line above sends a reminder at month 11.

---

## Step 10: Connect Clients

### Claude.ai (web)

1. Go to https://claude.ai -> Settings -> Connectors -> **Add custom connector**
2. Enter URL: `https://mcp.assist.uber.space/mcp`
3. Click **Connect** -> GitHub OAuth flow opens automatically
4. Authorize with your GitHub account
5. The connector appears as active — tools are now available in conversations

### Claude Mobile (iOS / Android)

Servers **cannot** be added directly from the mobile app. Add via claude.ai web first
(steps above), then:

1. Open Claude app on your phone
2. The connector syncs automatically from your account
3. Tools, prompts, and resources from the gateway are available in mobile conversations

### Claude Code CLI

```bash
claude mcp add trading-gateway --transport http https://mcp.assist.uber.space/mcp
claude mcp auth trading-gateway  # triggers OAuth flow in browser
```

### Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "trading-gateway": {
      "url": "https://mcp.assist.uber.space/mcp"
    }
  }
}
```

### Test it (any client)

> "Check the service status on the Uberspace server"

Claude uses the Bash tool to run `supervisorctl status` directly on the server.

---

## Step 11: Verify End-to-End

```bash
# Gateway running
supervisorctl status mcp-gateway

# HTTP endpoint responds
curl -s -o /dev/null -w "%{http_code}" https://mcp.assist.uber.space/mcp

# OAuth discovery works
curl -s https://mcp.assist.uber.space/.well-known/oauth-protected-resource

# Check logs
tail -5 ~/logs/mcp-gateway.out.log
tail -5 ~/logs/mcp-gateway.err.log
```

---

## What Claude.ai Can Do Through This Gateway

| Task | How |
|------|-----|
| Check service status | `Bash: supervisorctl status` |
| View logs | `Read: ~/logs/mcp-store.out.log` |
| Restart a service | `Bash: supervisorctl restart librechat` |
| Deploy update | `Bash: ~/bin/ta pull` |
| Edit configuration | `Edit: ~/mcps/.env` then `Bash: supervisorctl restart ...` |
| Search codebase | `GrepTool: pattern in ~/mcps/src/` |
| Browse profiles | `Read: ~/mcps/profiles/europe/countries/DEU.json` |
| Git operations | `Bash: cd ~/mcps && git log --oneline -10` |
| Debug a crash | Read logs -> grep errors -> inspect code -> fix -> restart |
| Disk usage | `Bash: df -h && du -sh ~/mcps ~/LibreChat ~/logs` |
| Check MongoDB | `Bash: ~/mcps/venv/bin/python -c "from pymongo import ..."` |

No custom tools. Claude.ai reasons about what to do, executes via native tools.

---

## Security Model

| Layer | Mechanism |
|-------|-----------|
| Authentication | GitHub OAuth 2.1 via FastMCP GitHubProvider + DCR |
| Authorization | `ALLOWED_GITHUB_USERS` allowlist (default: on) |
| Token isolation | FastMCP issues its own JWTs — upstream GitHub tokens never exposed to clients |
| Transport | HTTPS only (Uberspace auto-TLS via Let's Encrypt) |
| Execution | Claude Code's built-in safety model |
| Origin | FastMCP validates Origin header per MCP spec |
| Consent | FastMCP shows consent screen before granting access |
| Auth token | `CLAUDE_CODE_OAUTH_TOKEN` at mode 600, never in `ANTHROPIC_API_KEY` |
| Client support | Web, iOS, Android, CLI, Desktop — all via same OAuth App |

### Auth rules

- **Never** set both `CLAUDE_CODE_OAUTH_TOKEN` and `ANTHROPIC_API_KEY` — auth conflict
- `~/mcps/.env` must stay at mode 600
- Do **not** use Claude subscription OAuth for LibreChat or third-party tools (ToS)
- Renew `setup-token` ~1 month before 1-year expiry

### Known FastMCP OAuth limitations (upstream, not our code)

These are issues in FastMCP's OAuth implementation that may affect the gateway:

| Issue | Impact | Workaround |
|-------|--------|------------|
| DCR registration may fail with Claude.ai remote connectors | Claude.ai can't complete OAuth flow | Test with `curl -X POST .../register`; if broken, wait for FastMCP fix or use Claude Code CLI instead |
| Client secret exposed to MCP clients via DCR | OAuth App secret is returned in DCR response | Use a dedicated OAuth App with no sensitive repo scopes; rotate secret if compromised |
| OAuth flow times out after 5 minutes | Slow users may fail to complete GitHub login in time | Retry the connection; no server-side fix available |
| In-memory token storage | Tokens lost on restart; no horizontal scaling | Single-instance deployment (fine for dev gateway); FastMCP may add persistent storage later |

These are upstream issues in FastMCP's `OAuthProxy` / `GitHubProvider`. Monitor
the [FastMCP repo](https://github.com/jlowin/fastmcp) for fixes. None are
blockers for a single-user dev gateway.

---

## Updating

```bash
# Update gateway + stack code
ta pull && supervisorctl restart mcp-gateway

# Update Claude Code CLI
npm update -g @anthropic-ai/claude-code

# Update FastMCP
~/mcps/venv/bin/pip install -U 'fastmcp>=3.0'
```

---

## Troubleshooting

### Gateway won't start

```bash
tail -50 ~/logs/mcp-gateway.err.log
cd ~/mcps && venv/bin/python -m src.gateway.server  # run interactively
```

Common issues:
- `fastmcp` too old -> `venv/bin/pip install -U 'fastmcp>=3.0'`
- `claude` not in PATH -> `which claude` (npm global bin must be in PATH)
- Port conflict -> `ss -tlnp | grep 8070`

### Auth failures / 401s

```bash
# Verify token works directly
CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-... claude -p "echo ok"

# Check expiry
cat ~/.claude/.credentials.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('expiresAt'))"

# Re-run setup if expired
claude setup-token
```

### OAuth flow fails

1. Verify callback URL in GitHub OAuth App matches exactly:
   `https://mcp.assist.uber.space/auth/callback` (points to OUR server, not Claude.ai)
2. Check env vars: `grep GH_OAUTH ~/mcps/.env`
3. Test OAuth discovery: `curl -s https://mcp.assist.uber.space/.well-known/oauth-protected-resource`
4. Test DCR endpoint: `curl -s -X POST https://mcp.assist.uber.space/register -H 'Content-Type: application/json' -d '{"client_name":"test","redirect_uris":["http://localhost"]}'`

### Subdomain not resolving

```bash
uberspace web domain list  # verify mcp.assist.uber.space is listed
uberspace web backend list  # verify routing to port 8070
```

---

## Uninstall

```bash
supervisorctl stop mcp-gateway
rm ~/etc/services.d/mcp-gateway.ini
supervisorctl update
uberspace web backend del mcp.assist.uber.space
uberspace web domain del mcp.assist.uber.space
rm -rf ~/mcps/src/gateway
```

---

## Files

| File | Purpose |
|------|---------|
| `src/gateway/__init__.py` | Package marker |
| `src/gateway/server.py` | FastMCP proxy (~60 lines) |
| `~/etc/services.d/mcp-gateway.ini` | Supervisord service config |
| `~/bin/claude-auth-daemon.sh` | Auth health monitor |
| `~/mcps/.env` | Secrets + config (mode 600) |

---

## References

- [Building custom connectors (Anthropic)](https://support.claude.com/en/articles/11503834-building-custom-connectors-via-remote-mcp-servers) — official guide for remote MCP + Claude.ai
- [About custom integrations (Anthropic)](https://support.anthropic.com/en/articles/11175166-about-custom-integrations-using-remote-mcp) — setup for Pro/Max/Team/Enterprise
- [FastMCP Proxy Servers](https://gofastmcp.com/servers/proxy) — `create_proxy()` docs
- [FastMCP OAuth Proxy](https://gofastmcp.com/servers/auth/oauth-proxy) — OAuthProxy / GitHubProvider / DCR flow
- [Uberspace Web Backends](https://manual.uberspace.de/web-backends/) — reverse proxy routing
- [Uberspace Domains](https://manual.uberspace.de/en/web-domains.html) — subdomain setup (`.uber.space` = no DNS needed)
- [claude mcp serve (#631)](https://github.com/anthropics/claude-code/issues/631) — serve mode discussion
- [claude-code-mcp (steipete)](https://github.com/steipete/claude-code-mcp) — Claude Code as MCP pattern
- [Claude Code MCP docs](https://code.claude.com/docs/en/mcp) — official MCP guide
