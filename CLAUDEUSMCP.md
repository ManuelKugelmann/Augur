# CLAUDEUSMCP.md — Dev Workflow: Remote MCP Gateway on Uberspace

**This is a dev/ops workflow tool, NOT part of the production TradingAssistant stack.**

It deploys a lightweight MCP gateway on Uberspace so that Claude.ai and Claude Code (web)
can manage the server remotely. Think of it as SSH-over-MCP for our dev workflow.

The gateway is **fully independent** — it has its own venv, its own supervisord service,
its own subdomain, and zero imports from the main TradingAssistant codebase. It only
interacts with the stack via subprocess calls (`ta`, `supervisorctl`, file reads).

---

## What This Does

Exposes an authenticated MCP server over HTTPS on Uberspace so that **Claude.ai** and
**Claude Code (web)** can manage the TradingAssistant deployment remotely — check status,
view logs, restart services, deploy updates, query profiles, run diagnostics.

**Why separate?** The main stack (LibreChat + 12 domain MCPs + signals store) is the
product. This gateway is our remote control for operating it. It should never block or
be blocked by main stack changes.

```
Claude.ai / Claude Code (web/CLI)
    |
    |  HTTPS + OAuth 2.1 Bearer Token
    |  Streamable HTTP transport
    v
https://mcp.assist.uber.space/mcp
    |
    |  Uberspace nginx reverse proxy (auto TLS)
    v
localhost:8070  (Python FastMCP gateway)
    |
    +-- subprocess: supervisorctl     (service management)
    +-- subprocess: ~/bin/ta          (ops CLI)
    +-- subprocess: git               (repo operations)
    +-- file reads: ~/logs/*          (log access)
    +-- file reads: ~/mcps/profiles/* (profile browsing)
    +-- httpx: localhost:3080         (LibreChat health check)
```

---

## Prerequisites

- Uberspace account (e.g. `assist.uber.space`)
- Python 3.9+ available (Uberspace default)
- A GitHub OAuth App (created in Step 1 below)
- The main TradingAssistant stack at `~/mcps/` for full tool set (profile browsing,
  `ta` commands, data sync). Without it, only supervisorctl-based tools work.

---

## Step 0: Deploy the Gateway

The gateway lives at **`~/mcp-gateway/`** — a separate directory from the main stack.
It has its own venv, its own git checkout, and no Python imports from `~/mcps/`.

```bash
# Fresh checkout — gateway code only
mkdir -p ~/mcp-gateway && cd ~/mcp-gateway
git clone --depth 1 --filter=blob:none --sparse \
  https://github.com/ManuelKugelmann/TradingAssistant.git .
git sparse-checkout set src/gateway CLAUDEUSMCP.md
```

> The gateway interacts with the main stack only via subprocess (`~/bin/ta`, `supervisorctl`)
> and file reads (`~/mcps/profiles/`, `~/logs/`). If `~/mcps/` doesn't exist, the profile
> and deploy tools gracefully return "not found" messages.

For the rest of this guide, `$GW_DIR` = `~/mcp-gateway`.

---

## Step 1: Create GitHub OAuth App

1. Go to https://github.com/settings/developers
2. Click **New OAuth App**
3. Fill in:
   - **Application name**: `TradingAssistant MCP Gateway`
   - **Homepage URL**: `https://mcp.assist.uber.space`
   - **Authorization callback URL**: `https://claude.ai/api/mcp/auth_callback`
4. Click **Register application**
5. Copy the **Client ID**
6. Click **Generate a new client secret**, copy it
7. Save both values — you'll need them in Step 4

> **For Claude Code CLI**: Add a second callback URL if needed:
> `http://localhost:29107/oauth/callback` (or whatever `--callback-port` you use).
> GitHub OAuth Apps support only one callback URL, so for CLI testing you may need
> a second OAuth App or use the `--header` bearer token approach instead.

---

## Step 2: Set Up Python Environment

The gateway has its **own venv** at `~/mcp-gateway/venv/`, independent from `~/mcps/venv/`.

```bash
cd ~/mcp-gateway

# Create dedicated venv
python3 -m venv venv

# Install gateway dependencies (minimal — no pymongo required for core tools)
venv/bin/pip install -q 'fastmcp>=2.11' 'httpx>=0.27' 'python-dotenv>=1.0'

# Optional: pymongo for db_stats tool
venv/bin/pip install -q 'pymongo>=4.7'
```

> `fastmcp>=2.11` is required for OAuth support (`OAuthProxy` / `RemoteAuthProvider`).
> This is intentionally separate from the main stack's `requirements.txt` to avoid
> version coupling.

---

## Step 3: Create the Gateway Server

Create the directory structure:

```bash
mkdir -p ~/mcp-gateway/src/gateway/tools
touch ~/mcp-gateway/src/gateway/__init__.py
touch ~/mcp-gateway/src/gateway/tools/__init__.py
```

### `src/gateway/server.py` — Main entry point

```python
"""Remote MCP Gateway — ops tools for TradingAssistant on Uberspace.

Run: python src/gateway/server.py
Listens on $GATEWAY_PORT (default 8070) with Streamable HTTP transport.
"""
import os
import sys

from dotenv import load_dotenv
load_dotenv()

from fastmcp import FastMCP

# Import auth setup
from src.gateway.auth import get_auth_provider

# Create server
auth = get_auth_provider()
mcp = FastMCP(
    "TradingAssistant Gateway",
    instructions=(
        "Remote ops gateway for the TradingAssistant deployment on Uberspace. "
        "Provides service management, log viewing, deployment, and diagnostics."
    ),
    auth=auth,
)

# Register all tool modules
from src.gateway.tools import ops, deploy, diagnostics, data, config  # noqa: F401,E402

# Each module registers tools on `mcp` via import-time decoration.
# See individual modules for tool definitions.

if __name__ == "__main__":
    port = int(os.environ.get("GATEWAY_PORT", "8070"))
    host = os.environ.get("GATEWAY_HOST", "0.0.0.0")
    mcp.run(transport="streamable-http", host=host, port=port)
```

### `src/gateway/auth.py` — OAuth configuration

```python
"""OAuth configuration for the MCP gateway.

Uses GitHub OAuth via FastMCP's OAuthProxy to bridge GitHub's lack of
Dynamic Client Registration (DCR) with Claude.ai's DCR requirement.
"""
import os
from fastmcp.server.auth import OAuthProxy


def get_auth_provider():
    """Return configured OAuthProxy, or None if credentials not set."""
    client_id = os.environ.get("GH_OAUTH_CLIENT_ID")
    client_secret = os.environ.get("GH_OAUTH_CLIENT_SECRET")

    if not client_id or not client_secret:
        import warnings
        warnings.warn(
            "GH_OAUTH_CLIENT_ID / GH_OAUTH_CLIENT_SECRET not set. "
            "Running WITHOUT authentication. Do NOT expose to the internet.",
            stacklevel=2,
        )
        return None

    allowed = os.environ.get("GATEWAY_ALLOWED_USERS", "ManuelKugelmann")
    allowed_users = [u.strip() for u in allowed.split(",") if u.strip()]
    base_url = os.environ.get("GATEWAY_BASE_URL", "https://mcp.assist.uber.space")

    return OAuthProxy(
        client_id=client_id,
        client_secret=client_secret,
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        allowed_users=allowed_users,
        base_url=base_url,
    )
```

### `src/gateway/security.py` — Confirmation tokens, redaction, audit

```python
"""Security utilities: confirmation tokens, secret redaction, audit logging."""
import hashlib
import os
import re
import time
from pathlib import Path

# Confirmation tokens for dangerous operations
_pending_confirmations: dict[str, dict] = {}
_TOKEN_TTL = 300  # 5 minutes

AUDIT_LOG = Path(os.environ.get(
    "GATEWAY_AUDIT_LOG",
    os.path.expanduser("~/logs/mcp-gateway.audit.log")
))

# Patterns for secret redaction
_SECRET_PATTERNS = re.compile(
    r'(SECRET|KEY|PASSWORD|TOKEN|URI|MONGO|CREDS)',
    re.IGNORECASE
)


def create_confirmation(action: str, details: str) -> str:
    """Create a confirmation token for a dangerous operation."""
    token = hashlib.sha256(f"{action}:{time.time()}:{os.urandom(8).hex()}".encode()).hexdigest()[:16]
    _pending_confirmations[token] = {
        "action": action,
        "details": details,
        "created": time.time(),
    }
    # Prune expired tokens
    now = time.time()
    expired = [k for k, v in _pending_confirmations.items() if now - v["created"] > _TOKEN_TTL]
    for k in expired:
        del _pending_confirmations[k]
    return token


def verify_confirmation(token: str, action: str) -> bool:
    """Verify and consume a confirmation token."""
    info = _pending_confirmations.pop(token, None)
    if not info:
        return False
    if info["action"] != action:
        return False
    if time.time() - info["created"] > _TOKEN_TTL:
        return False
    return True


def redact_secrets(text: str) -> str:
    """Redact values of env-like lines where the key matches secret patterns."""
    lines = []
    for line in text.splitlines():
        if "=" in line:
            key = line.split("=", 1)[0].strip()
            if _SECRET_PATTERNS.search(key):
                lines.append(f"{key}=***REDACTED***")
                continue
        lines.append(line)
    return "\n".join(lines)


def audit(tool: str, args: dict, result_summary: str):
    """Append an audit log entry."""
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        entry = f"{ts} tool={tool} args={args} result={result_summary}\n"
        with open(AUDIT_LOG, "a") as f:
            f.write(entry)
    except Exception:
        pass  # Audit logging must never break the tool
```

### `src/gateway/tools/ops.py` — Service operations (Tier 1)

```python
"""Tier 1 tools: status, restart, logs, version."""
import subprocess
from src.gateway.server import mcp
from src.gateway.security import audit


def _run(cmd: list[str], timeout: int = 30) -> str:
    """Run a command and return stdout. Never raises."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return f"ERROR: command timed out after {timeout}s"
    except Exception as e:
        return f"ERROR: {e}"


@mcp.tool()
def status() -> str:
    """Show service status, version, and uptime for all managed services."""
    out = _run(["supervisorctl", "status"])
    version = _run(["cat", f"{_home()}/LibreChat/.version"]).strip()
    audit("status", {}, f"version={version}")
    return f"## Services\n```\n{out}```\n\n**Version**: {version}"


@mcp.tool()
def restart(service: str = "librechat") -> str:
    """Restart a managed service. Default: librechat.

    Args:
        service: Service name (librechat, mcp-store, mcp-weather, etc.)
    """
    allowed = _allowed_services()
    if service not in allowed:
        return f"Unknown service '{service}'. Available: {', '.join(sorted(allowed))}"
    out = _run(["supervisorctl", "restart", service])
    audit("restart", {"service": service}, out.strip())
    return out


@mcp.tool()
def logs(service: str = "librechat", lines: int = 100) -> str:
    """Tail recent log output for a service.

    Args:
        service: Service name
        lines: Number of lines to return (max 500)
    """
    lines = min(lines, 500)
    log_path = f"{_home()}/logs/{service}.out.log"
    out = _run(["tail", "-n", str(lines), log_path])
    if "No such file" in out or "cannot open" in out:
        # Try .err.log
        log_path = f"{_home()}/logs/{service}.err.log"
        out = _run(["tail", "-n", str(lines), log_path])
    audit("logs", {"service": service, "lines": lines}, f"{len(out)} chars")
    return f"```\n{out}```"


@mcp.tool()
def version() -> str:
    """Show the currently deployed version."""
    v = _run(["cat", f"{_home()}/LibreChat/.version"]).strip()
    audit("version", {}, v)
    return v


def _home() -> str:
    import os
    return os.path.expanduser("~")


def _allowed_services() -> set:
    """Parse supervisorctl status to get known service names."""
    out = _run(["supervisorctl", "status"])
    services = set()
    for line in out.splitlines():
        parts = line.split()
        if parts:
            services.add(parts[0])
    return services
```

### `src/gateway/tools/deploy.py` — Deployment operations (Tier 1)

```python
"""Tier 1 tools: deploy_update, deploy_pull, deploy_rollback."""
import os
from src.gateway.server import mcp
from src.gateway.security import create_confirmation, verify_confirmation, audit
from src.gateway.tools.ops import _run


@mcp.tool()
def deploy_pull() -> str:
    """Quick dev update: git pull the stack repo and restart services.

    This runs `ta pull` which does a fast-forward git pull and restarts LibreChat.
    """
    out = _run([os.path.expanduser("~/bin/ta"), "pull"], timeout=120)
    audit("deploy_pull", {}, out[:200])
    return out


@mcp.tool()
def deploy_update() -> str:
    """Request a production release update.

    Returns a confirmation token. Call confirm_deploy(token) to execute.
    This downloads the latest GitHub Release and does an atomic swap.
    """
    token = create_confirmation("deploy_update", "Download latest release and swap")
    audit("deploy_update", {}, f"confirmation_requested token={token}")
    return (
        f"## Confirm Production Update\n\n"
        f"This will download the latest GitHub Release and atomically swap the deployment.\n\n"
        f"To proceed, call: `confirm_deploy(token=\"{token}\")`\n\n"
        f"Token expires in 5 minutes."
    )


@mcp.tool()
def confirm_deploy(token: str) -> str:
    """Confirm and execute a production update or rollback.

    Args:
        token: Confirmation token from deploy_update() or deploy_rollback()
    """
    if verify_confirmation(token, "deploy_update"):
        out = _run([os.path.expanduser("~/bin/ta"), "u"], timeout=300)
        audit("confirm_deploy", {"action": "update"}, out[:200])
        return out
    elif verify_confirmation(token, "deploy_rollback"):
        out = _run([os.path.expanduser("~/bin/ta"), "rb"], timeout=60)
        audit("confirm_deploy", {"action": "rollback"}, out[:200])
        return out
    else:
        return "Invalid or expired confirmation token."


@mcp.tool()
def deploy_rollback() -> str:
    """Request a rollback to the previous version.

    Returns a confirmation token. Call confirm_deploy(token) to execute.
    """
    token = create_confirmation("deploy_rollback", "Rollback to previous version")
    audit("deploy_rollback", {}, f"confirmation_requested token={token}")
    return (
        f"## Confirm Rollback\n\n"
        f"This will swap back to the previous deployment.\n\n"
        f"To proceed, call: `confirm_deploy(token=\"{token}\")`\n\n"
        f"Token expires in 5 minutes."
    )
```

### `src/gateway/tools/diagnostics.py` — System diagnostics (Tier 2)

```python
"""Tier 2 tools: disk_usage, memory_usage, health_check, cron_status, error_scan."""
import os
from src.gateway.server import mcp
from src.gateway.security import audit
from src.gateway.tools.ops import _run


@mcp.tool()
def disk_usage() -> str:
    """Show disk space summary and sizes of key directories."""
    df = _run(["df", "-h", os.path.expanduser("~")])
    dirs = ["~/mcps", "~/LibreChat", "~/TradeAssistant_Data", "~/logs"]
    sizes = []
    for d in dirs:
        expanded = os.path.expanduser(d)
        if os.path.isdir(expanded):
            size = _run(["du", "-sh", expanded]).split()[0] if os.path.isdir(expanded) else "N/A"
            sizes.append(f"  {d}: {size}")
    audit("disk_usage", {}, "ok")
    return f"## Disk\n```\n{df}```\n\n## Directories\n" + "\n".join(sizes)


@mcp.tool()
def memory_usage() -> str:
    """Show RAM usage for managed processes."""
    out = _run(["ps", "aux", "--sort=-rss"])
    # Filter to our processes
    lines = [out.splitlines()[0]]  # header
    keywords = ["python", "node", "librechat", "mcp-", "supervisord"]
    for line in out.splitlines()[1:]:
        if any(kw in line.lower() for kw in keywords):
            lines.append(line)
    audit("memory_usage", {}, f"{len(lines)-1} processes")
    return f"```\n" + "\n".join(lines) + "\n```"


@mcp.tool()
def health_check() -> str:
    """Run an end-to-end health check: supervisord, MongoDB, LibreChat HTTP."""
    results = []

    # 1. Supervisord
    sup = _run(["supervisorctl", "status"])
    running = sum(1 for l in sup.splitlines() if "RUNNING" in l)
    total = len([l for l in sup.splitlines() if l.strip()])
    results.append(f"Supervisord: {running}/{total} services RUNNING")

    # 2. LibreChat HTTP
    import httpx
    try:
        r = httpx.get("http://localhost:3080/api/health", timeout=5)
        results.append(f"LibreChat HTTP: {r.status_code}")
    except Exception as e:
        results.append(f"LibreChat HTTP: FAILED ({e})")

    # 3. MongoDB ping
    try:
        from pymongo import MongoClient
        uri = os.environ.get("MONGO_URI", "")
        if uri:
            client = MongoClient(uri, serverSelectionTimeoutMS=5000)
            client.admin.command("ping")
            results.append("MongoDB: OK (ping successful)")
            client.close()
        else:
            results.append("MongoDB: SKIP (MONGO_URI not set)")
    except Exception as e:
        results.append(f"MongoDB: FAILED ({e})")

    audit("health_check", {}, "; ".join(results))
    return "## Health Check\n\n" + "\n".join(f"- {r}" for r in results)


@mcp.tool()
def cron_status() -> str:
    """Show last data sync time and cron log entries."""
    # Last sync commit
    data_dir = os.path.expanduser("~/TradeAssistant_Data")
    last_sync = "N/A"
    if os.path.isdir(os.path.join(data_dir, ".git")):
        last_sync = _run(["git", "-C", data_dir, "log", "-1", "--format=%ci %s"]).strip()

    # Recent cron log entries
    cron_log = _run(["journalctl", "-t", "ta-cron", "-n", "20", "--no-pager"])
    if "No entries" in cron_log or "Failed" in cron_log:
        cron_log = "(no journalctl entries — check logger -t ta-cron)"

    audit("cron_status", {}, f"last_sync={last_sync[:30]}")
    return f"## Last Data Sync\n{last_sync}\n\n## Recent Cron Log\n```\n{cron_log}```"


@mcp.tool()
def error_scan(hours: int = 24) -> str:
    """Grep recent logs for errors.

    Args:
        hours: How far back to scan (default 24h, max 168h)
    """
    hours = min(hours, 168)
    log_dir = os.path.expanduser("~/logs")
    if not os.path.isdir(log_dir):
        return "No log directory found."

    # Find log files modified in the last N hours
    import glob
    import time
    cutoff = time.time() - (hours * 3600)
    errors = []
    for path in glob.glob(f"{log_dir}/*.log"):
        if os.path.getmtime(path) < cutoff:
            continue
        out = _run(["grep", "-i", "-c", "error", path])
        count = out.strip()
        if count.isdigit() and int(count) > 0:
            # Get last few error lines
            sample = _run(["grep", "-i", "-m", "5", "error", path])
            errors.append(f"### {os.path.basename(path)} ({count} errors)\n```\n{sample}```")

    audit("error_scan", {"hours": hours}, f"{len(errors)} files with errors")
    if not errors:
        return f"No errors found in logs from the last {hours}h."
    return f"## Errors (last {hours}h)\n\n" + "\n\n".join(errors)
```

### `src/gateway/tools/data.py` — Data & profile operations (Tier 3)

```python
"""Tier 3 tools: list_profiles, get_profile, data_sync, db_stats."""
import json
import os
from pathlib import Path
from src.gateway.server import mcp
from src.gateway.security import audit
from src.gateway.tools.ops import _run

PROFILES_DIR = Path(os.environ.get("PROFILES_DIR", os.path.expanduser("~/mcps/profiles")))


@mcp.tool()
def list_profiles(kind: str = "", region: str = "") -> str:
    """List available profiles, optionally filtered by kind and/or region.

    Args:
        kind: Profile kind (countries, stocks, etfs, etc.). Empty = all kinds.
        region: Region filter (europe, north_america, etc.). Empty = all regions.
    """
    results = []
    search_dir = PROFILES_DIR

    if not search_dir.is_dir():
        return f"Profiles directory not found: {search_dir}"

    for region_dir in sorted(search_dir.iterdir()):
        if not region_dir.is_dir() or region_dir.name.startswith((".", "SCHEMA", "INDEX")):
            continue
        if region and region_dir.name != region:
            continue
        for kind_dir in sorted(region_dir.iterdir()):
            if not kind_dir.is_dir():
                continue
            if kind and kind_dir.name != kind:
                continue
            profiles = sorted(kind_dir.glob("*.json"))
            if profiles:
                names = [p.stem for p in profiles]
                results.append(f"**{region_dir.name}/{kind_dir.name}**: {', '.join(names)}")

    audit("list_profiles", {"kind": kind, "region": region}, f"{len(results)} groups")
    return "\n".join(results) if results else "No profiles found."


@mcp.tool()
def get_profile(kind: str, id: str, region: str = "") -> str:
    """Read a profile by kind and ID.

    Args:
        kind: Profile kind (countries, stocks, etc.)
        id: Profile ID (DEU, AAPL, etc.)
        region: Region (optional, scans all if omitted)
    """
    if region:
        path = PROFILES_DIR / region / kind / f"{id}.json"
        if path.is_file():
            data = json.loads(path.read_text())
            audit("get_profile", {"kind": kind, "id": id, "region": region}, "found")
            return json.dumps(data, indent=2)
    else:
        for region_dir in PROFILES_DIR.iterdir():
            if not region_dir.is_dir() or region_dir.name.startswith((".", "SCHEMA", "INDEX")):
                continue
            path = region_dir / kind / f"{id}.json"
            if path.is_file():
                data = json.loads(path.read_text())
                audit("get_profile", {"kind": kind, "id": id}, f"found in {region_dir.name}")
                return json.dumps(data, indent=2)

    audit("get_profile", {"kind": kind, "id": id}, "not_found")
    return f"Profile not found: {kind}/{id}"


@mcp.tool()
def data_sync() -> str:
    """Force git push of the data repository to GitHub."""
    out = _run([os.path.expanduser("~/bin/ta"), "sync"], timeout=60)
    audit("data_sync", {}, out[:200])
    return out


@mcp.tool()
def db_stats() -> str:
    """Show MongoDB collection statistics (document counts, sizes)."""
    try:
        from pymongo import MongoClient
        uri = os.environ.get("MONGO_URI", "")
        if not uri:
            return "MONGO_URI not set."
        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        db = client.signals
        collections = db.list_collection_names()
        stats = []
        for name in sorted(collections):
            s = db.command("collStats", name)
            stats.append(f"  {name}: {s.get('count', '?')} docs, {s.get('storageSize', 0) // 1024}KB")
        client.close()
        audit("db_stats", {}, f"{len(collections)} collections")
        return "## MongoDB (signals db)\n\n" + "\n".join(stats)
    except Exception as e:
        audit("db_stats", {}, f"error: {e}")
        return f"MongoDB error: {e}"
```

### `src/gateway/tools/config.py` — Configuration (Tier 4, guarded)

```python
"""Tier 4 tools: get_config, set_env."""
import os
from src.gateway.server import mcp
from src.gateway.security import redact_secrets, create_confirmation, verify_confirmation, audit


@mcp.tool()
def get_config(file: str = "stack") -> str:
    """Read a configuration file with secrets redacted.

    Args:
        file: Which config to read. Options:
              "stack"  = ~/mcps/.env
              "app"    = ~/LibreChat/.env
              "deploy" = ~/mcps/deploy.conf
              "yaml"   = ~/LibreChat/librechat.yaml
    """
    paths = {
        "stack": os.path.expanduser("~/mcps/.env"),
        "app": os.path.expanduser("~/LibreChat/.env"),
        "deploy": os.path.expanduser("~/mcps/deploy.conf"),
        "yaml": os.path.expanduser("~/LibreChat/librechat.yaml"),
    }
    path = paths.get(file)
    if not path:
        return f"Unknown config file '{file}'. Options: {', '.join(paths.keys())}"
    if not os.path.isfile(path):
        return f"File not found: {path}"

    with open(path) as f:
        content = f.read()

    # Redact secrets in .env files
    if file in ("stack", "app"):
        content = redact_secrets(content)

    audit("get_config", {"file": file}, f"{len(content)} chars")
    return f"## {path}\n```\n{content}\n```"


@mcp.tool()
def set_env(key: str, value: str, file: str = "stack") -> str:
    """Request to update an environment variable. Returns confirmation token.

    Args:
        key: Environment variable name
        value: New value
        file: "stack" (~/mcps/.env) or "app" (~/LibreChat/.env)
    """
    if file not in ("stack", "app"):
        return "file must be 'stack' or 'app'"

    token = create_confirmation("set_env", f"{file}:{key}={value}")
    audit("set_env", {"key": key, "file": file}, f"confirmation_requested token={token}")
    return (
        f"## Confirm Environment Change\n\n"
        f"Set `{key}` in {file} .env\n\n"
        f"To proceed, call: `confirm_set_env(token=\"{token}\")`\n\n"
        f"Token expires in 5 minutes."
    )


@mcp.tool()
def confirm_set_env(token: str) -> str:
    """Confirm and execute an environment variable change.

    Args:
        token: Confirmation token from set_env()
    """
    # Find matching pending confirmation
    from src.gateway.security import _pending_confirmations
    info = _pending_confirmations.get(token)
    if not info or info["action"] != "set_env":
        return "Invalid or expired confirmation token."

    details = info["details"]
    file_key, kv = details.split(":", 1)
    key, value = kv.split("=", 1)

    paths = {
        "stack": os.path.expanduser("~/mcps/.env"),
        "app": os.path.expanduser("~/LibreChat/.env"),
    }
    path = paths[file_key]

    if not verify_confirmation(token, "set_env"):
        return "Invalid or expired confirmation token."

    # Read, update, write
    lines = []
    found = False
    if os.path.isfile(path):
        with open(path) as f:
            for line in f:
                if line.startswith(f"{key}="):
                    lines.append(f"{key}={value}\n")
                    found = True
                else:
                    lines.append(line)
    if not found:
        lines.append(f"{key}={value}\n")

    with open(path, "w") as f:
        f.writelines(lines)

    audit("confirm_set_env", {"key": key, "file": file_key}, "applied")
    return f"Set `{key}` in {path}. Restart the relevant service for changes to take effect."
```

---

## Step 4: Configure Environment

Create the gateway's own `.env`:

```bash
cat > ~/mcp-gateway/.env << 'EOF'

# ── MCP Gateway ──────────────────────────────
GH_OAUTH_CLIENT_ID=Iv1.xxxxxxxxxxxxxxxx
GH_OAUTH_CLIENT_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
GATEWAY_ALLOWED_USERS=ManuelKugelmann
GATEWAY_PORT=8070
GATEWAY_BASE_URL=https://mcp.assist.uber.space
GATEWAY_AUDIT_LOG=/home/assist/logs/mcp-gateway.audit.log
EOF
```

> Replace the `GH_OAUTH_*` values with the ones from Step 1.

---

## Step 5: Register Subdomain

```bash
# Add the subdomain (Uberspace handles TLS automatically)
uberspace web domain add mcp.assist.uber.space
```

> **If subdomain fails** (DNS not configured): Use path-based routing instead:
> ```bash
> uberspace web backend set /mcp-gateway --http --port 8070
> ```
> And set `GATEWAY_BASE_URL=https://assist.uber.space/mcp-gateway` in `.env`.

### DNS Setup (if using subdomain)

Add a CNAME record in your DNS provider:
```
mcp.assist.uber.space.  CNAME  assist.uber.space.
```

Uberspace handles TLS via Let's Encrypt once the domain resolves.

---

## Step 6: Create Supervisord Service

```bash
cat > ~/etc/services.d/mcp-gateway.ini << 'EOF'
[program:mcp-gateway]
directory=%(ENV_HOME)s/mcp-gateway
command=%(ENV_HOME)s/mcp-gateway/venv/bin/python -m src.gateway.server
environment=PORT=8070
autostart=true
autorestart=true
stderr_logfile=%(ENV_HOME)s/logs/mcp-gateway.err.log
stdout_logfile=%(ENV_HOME)s/logs/mcp-gateway.out.log
EOF
```

```bash
# Create log directory
mkdir -p ~/logs

# Register and start
supervisorctl reread
supervisorctl add mcp-gateway
supervisorctl start mcp-gateway
```

---

## Step 7: Set Up Reverse Proxy

```bash
# Route subdomain to gateway port
uberspace web backend set mcp.assist.uber.space --http --port 8070
```

### Verify it's running

```bash
# Check supervisord
supervisorctl status mcp-gateway

# Test HTTP (should return MCP server info or 401)
curl -s https://mcp.assist.uber.space/mcp
```

---

## Step 8: Connect Claude.ai

1. Go to https://claude.ai
2. Settings -> Connectors -> **Add custom connector**
3. Enter URL: `https://mcp.assist.uber.space/mcp`
4. Click Connect — GitHub OAuth flow opens
5. Authorize the app with your GitHub account
6. The connector appears with all gateway tools

### Test it

In a Claude.ai conversation:
> "Use the TradingAssistant Gateway to check the service status"

Claude will call the `status()` tool and return supervisord output + version.

---

## Step 9: Connect Claude Code (CLI)

```bash
# Add the remote MCP server
claude mcp add trading-gateway --transport http https://mcp.assist.uber.space/mcp

# Authenticate (opens browser for GitHub OAuth)
claude mcp auth trading-gateway
```

### Alternative: Bearer token (no OAuth)

If OAuth is not configured (dev/testing), use a static header:

```bash
claude mcp add trading-gateway \
  --transport http \
  --header "Authorization: Bearer $MY_STATIC_TOKEN" \
  https://mcp.assist.uber.space/mcp
```

> This only works if you implement custom bearer token validation in `auth.py`.
> The default setup requires OAuth.

---

## Step 10: Verify End-to-End

Run these checks after deployment:

```bash
# 1. Gateway process is running
supervisorctl status mcp-gateway
# Expected: mcp-gateway  RUNNING  pid XXXX, uptime X:XX:XX

# 2. HTTP endpoint responds
curl -s -o /dev/null -w "%{http_code}" https://mcp.assist.uber.space/mcp
# Expected: 401 (OAuth required) or 200 (if no auth configured)

# 3. OAuth discovery endpoint exists
curl -s https://mcp.assist.uber.space/.well-known/oauth-protected-resource
# Expected: JSON with authorization_servers

# 4. Logs are being written
tail -5 ~/logs/mcp-gateway.out.log
tail -5 ~/logs/mcp-gateway.err.log

# 5. Audit log works (after first tool call)
cat ~/logs/mcp-gateway.audit.log
```

---

## Updating the Gateway

The gateway updates independently from the main stack.

```bash
cd ~/mcp-gateway && git pull && supervisorctl restart mcp-gateway
```

This does NOT affect the main TradingAssistant stack or LibreChat.

---

## Tool Reference

### Tier 1 — Service Operations
| Tool | Description |
|------|-------------|
| `status()` | Service status, version, uptime |
| `restart(service?)` | Restart a service (default: librechat) |
| `logs(service, lines?)` | Tail recent logs (max 500 lines) |
| `version()` | Current deployed version |
| `deploy_pull()` | Quick dev update via git pull |
| `deploy_update()` | Request production release update (needs confirmation) |
| `deploy_rollback()` | Request rollback (needs confirmation) |
| `confirm_deploy(token)` | Execute a confirmed deploy/rollback |

### Tier 2 — Diagnostics
| Tool | Description |
|------|-------------|
| `disk_usage()` | Disk space + key directory sizes |
| `memory_usage()` | RAM per managed process |
| `health_check()` | Supervisord + MongoDB + LibreChat HTTP |
| `cron_status()` | Last data sync + cron log |
| `error_scan(hours?)` | Grep logs for errors (default: 24h) |

### Tier 3 — Data & Profiles
| Tool | Description |
|------|-------------|
| `list_profiles(kind?, region?)` | Browse profile inventory |
| `get_profile(kind, id, region?)` | Read a profile JSON |
| `data_sync()` | Force git push of data repo |
| `db_stats()` | MongoDB collection stats |

### Tier 4 — Configuration (guarded)
| Tool | Description |
|------|-------------|
| `get_config(file)` | Read config (secrets redacted) |
| `set_env(key, value, file?)` | Update env var (needs confirmation) |
| `confirm_set_env(token)` | Execute confirmed env change |

---

## Security Model

| Layer | Mechanism |
|-------|-----------|
| Authentication | GitHub OAuth 2.1 via FastMCP OAuthProxy |
| Authorization | User allowlist (`GATEWAY_ALLOWED_USERS`) |
| Transport | HTTPS only (Uberspace auto-TLS via Let's Encrypt) |
| Dangerous ops | Confirmation tokens (deploy, rollback, set_env) with 5-min TTL |
| Secret protection | Automatic redaction in `get_config` for keys matching SECRET/KEY/PASSWORD/TOKEN/URI/MONGO/CREDS |
| Audit trail | All tool calls logged to `~/logs/mcp-gateway.audit.log` |
| No arbitrary exec | No shell/eval tool. All commands are hardcoded subprocess calls |
| Origin validation | FastMCP validates Origin header per MCP spec |

---

## Troubleshooting

### Gateway won't start

```bash
# Check logs
tail -50 ~/logs/mcp-gateway.err.log

# Test manually
cd ~/mcp-gateway && venv/bin/python -m src.gateway.server
# Look for import errors, missing deps, port conflicts
```

### OAuth flow fails on Claude.ai

1. Verify callback URL in GitHub OAuth App: `https://claude.ai/api/mcp/auth_callback`
2. Check that `GH_OAUTH_CLIENT_ID` and `GH_OAUTH_CLIENT_SECRET` are correct
3. Verify the gateway is reachable: `curl https://mcp.assist.uber.space/mcp`
4. Check `/.well-known/oauth-protected-resource` returns valid JSON

### `.well-known` endpoint not found

FastMCP serves this at the server root. If using path-based routing
(`/mcp-gateway`), the well-known endpoint may be at
`assist.uber.space/mcp-gateway/.well-known/oauth-protected-resource` instead
of the domain root. Some clients only check the domain root.

**Fix**: Use a subdomain (`mcp.assist.uber.space`) where the gateway is at `/`.

### Port conflict

```bash
# Check what's using port 8070
ss -tlnp | grep 8070

# Change port in .env and supervisord .ini, then:
supervisorctl reread && supervisorctl restart mcp-gateway
uberspace web backend set mcp.assist.uber.space --http --port NEW_PORT
```

### FastMCP OAuthProxy import error

```bash
# Ensure fastmcp >= 2.11
~/mcp-gateway/venv/bin/pip show fastmcp | grep Version

# Upgrade if needed
~/mcp-gateway/venv/bin/pip install -U 'fastmcp>=2.11'
```

### Gateway tools show "command timed out"

Default timeout is 30s per subprocess call. Long operations (`ta u`) use 300s.
If Uberspace is slow, increase the timeout in the tool implementation.

---

## Uninstall

```bash
# Stop and remove service
supervisorctl stop mcp-gateway
rm ~/etc/services.d/mcp-gateway.ini
supervisorctl reread

# Remove web backend
uberspace web backend del mcp.assist.uber.space

# Remove subdomain (optional)
uberspace web domain del mcp.assist.uber.space

# Remove gateway code and venv
rm -rf ~/mcp-gateway

# Remove audit log
rm ~/logs/mcp-gateway.audit.log
```

---

## Files Created by This Guide

| File | Purpose |
|------|---------|
| `src/gateway/__init__.py` | Package marker |
| `src/gateway/server.py` | FastMCP server entry point |
| `src/gateway/auth.py` | GitHub OAuth configuration |
| `src/gateway/security.py` | Confirmation tokens, redaction, audit |
| `src/gateway/tools/__init__.py` | Package marker |
| `src/gateway/tools/ops.py` | status, restart, logs, version |
| `src/gateway/tools/deploy.py` | deploy_pull, deploy_update, deploy_rollback |
| `src/gateway/tools/diagnostics.py` | disk, memory, health, cron, errors |
| `src/gateway/tools/data.py` | profiles, sync, db_stats |
| `src/gateway/tools/config.py` | get_config, set_env |
| `~/etc/services.d/mcp-gateway.ini` | Supervisord service definition |
| `~/logs/mcp-gateway.audit.log` | Audit trail (created at runtime) |
