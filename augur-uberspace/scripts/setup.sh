#!/bin/bash
# LibreChat Lite — install or update on Uberspace
# Called by Augur.sh (_lc_download_and_setup) or directly: bash setup.sh <app-dir> <version>
set -euo pipefail

# ── Load central config ──
for conf in "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/deploy.conf" \
            "$HOME/augur/deploy.conf"; do
    [[ -f "$conf" ]] && { source "$conf"; break; }
done

SRC="${1:?Usage: setup.sh <app-dir> <version>}"
VER="${2:-unknown}"
APP="${APP_DIR:-$HOME/LibreChat}"
STACK="${STACK_DIR:-$HOME/augur}"
PORT="${LC_PORT:-3080}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
die()  { echo -e "${RED}✗${NC} $1" >&2; exit 1; }

# ── Service management (systemd) ──
_svc_stop_lc()  { systemctl --user stop librechat || true; }
_svc_start_lc() { systemctl --user start librechat || true; }
_web_backend() {
    local path="$1" port="$2"
    timeout 30 uberspace web backend add "$path" port "$port" --force
}

# Files and dirs that survive updates
PERSIST_FILES=(.env librechat.yaml librechat-user.yaml .version .asset_ts)
PERSIST_DIRS=(uploads logs images)

# ── Pre-flight ──────────────────────────────
command -v node &>/dev/null || die "Node.js not found (system-provided on Uberspace)."
NODE_MAJOR=$(node -v | cut -d. -f1 | tr -d 'v')
[[ "$NODE_MAJOR" -lt 20 ]] && die "Node.js ≥20 required (got $(node -v))."

# ── Detect mode ─────────────────────────────
if [[ -d "$APP" ]]; then
    MODE="update"
    log "Updating to ${VER}..."
else
    MODE="install"
    log "Installing ${VER}..."
fi

# ── Stop service and prepare ────────────────
if [[ "$MODE" == "update" ]]; then
    log "  → stopping librechat service"
    _svc_stop_lc
    sleep 2

    # Preserve user config and persistent dirs in a small temp dir
    _cfg_tmp=$(mktemp -d)
    for f in "${PERSIST_FILES[@]}"; do
        [[ -f "$APP/$f" ]] && { log "  → preserving $f"; cp "$APP/$f" "$_cfg_tmp/$f"; }
    done
    for d in "${PERSIST_DIRS[@]}"; do
        [[ -d "$APP/$d" ]] && { log "  → preserving $d/"; mv "$APP/$d" "$_cfg_tmp/$d"; }
    done

    # Delete old app entirely to free disk space before installing new
    log "  → removing old app"
    rm -rf "$APP"
fi

# ── Install new bundle ─────────────────────
log "  → installing: $SRC → $APP"
mv "$SRC" "$APP"

# Restore preserved config and dirs
if [[ -n "${_cfg_tmp:-}" && -d "${_cfg_tmp:-}" ]]; then
    for f in "${PERSIST_FILES[@]}"; do
        [[ -f "$_cfg_tmp/$f" ]] && cp "$_cfg_tmp/$f" "$APP/$f"
    done
    for d in "${PERSIST_DIRS[@]}"; do
        [[ -d "$_cfg_tmp/$d" ]] && { rm -rf "$APP/$d"; mv "$_cfg_tmp/$d" "$APP/$d"; }
    done
    rm -rf "$_cfg_tmp"
fi

for d in "${PERSIST_DIRS[@]}"; do mkdir -p "$APP/$d"; done

# ── Verify LibreChat app code is present ────
# The release bundle must include pre-built LibreChat (built in CI).
if [[ ! -f "$APP/api/server/index.js" ]]; then
    die "LibreChat app code missing from bundle. Use a release built with CI (git tag + push)."
fi

# ── Merge system + user config on every start ──
# System template (MCP servers, version, mcpSettings) always comes from repo.
# User overlay (LLM endpoints, registration, cache) is preserved across updates.
_SYS_YAML="$STACK/augur-uberspace/config/librechat-system.yaml"
_USR_YAML_SRC="$STACK/augur-uberspace/config/librechat-user.yaml"
_USR_YAML="$APP/librechat-user.yaml"
_MERGE_SCRIPT="$STACK/augur-uberspace/scripts/merge-librechat-yaml.py"
if [[ -f "$_SYS_YAML" ]] && [[ -f "$_MERGE_SCRIPT" ]]; then
    # Seed user overlay from template if missing
    if [[ ! -f "$_USR_YAML" ]] && [[ -f "$_USR_YAML_SRC" ]]; then
        cp "$_USR_YAML_SRC" "$_USR_YAML" && log "Created default librechat-user.yaml"
    fi
    # Find a working Python (venv preferred, then system)
    _MERGE_PY=""
    for _py in "$STACK/venv/bin/python" python3 python; do
        command -v "$_py" &>/dev/null && "$_py" -c "import yaml" 2>/dev/null && { _MERGE_PY="$_py"; break; }
    done
    if [[ -n "$_MERGE_PY" ]] && [[ -f "$_USR_YAML" ]]; then
        if "$_MERGE_PY" "$_MERGE_SCRIPT" "$_SYS_YAML" "$_USR_YAML" "$APP/librechat.yaml" "$HOME" 2>/dev/null; then
            log "Merged librechat.yaml (system + user, paths adjusted to $HOME)"
        else
            warn "Config merge failed — falling back to system template copy"
            cp "$_SYS_YAML" "$APP/librechat.yaml"
            sed -i "s|__HOME__|$HOME|g" "$APP/librechat.yaml"
        fi
    else
        warn "Python with PyYAML not found — falling back to system template copy"
        cp "$_SYS_YAML" "$APP/librechat.yaml"
        sed -i "s|__HOME__|$HOME|g" "$APP/librechat.yaml"
    fi
elif [[ ! -f "$APP/librechat.yaml" ]]; then
    warn "librechat config not found in mcps repo — configure manually"
fi

# ── Check prebuilt MCP Node servers ─────────────
# Node MCPs (rss, prediction-markets, hackernews, mcp-remote) are prebuilt
# via CI and downloaded by install.sh. No npm install needed here.
if [[ -d "$STACK/mcp-nodes/node_modules" ]]; then
    log "MCP Node servers bundle present"
else
    warn "MCP Node servers not found at $STACK/mcp-nodes — some MCPs won't be available"
    warn "Run: augur install (downloads mcp-nodes bundle)"
fi

# Python MCPs installed into signals stack venv
if [[ -d "$STACK/venv" ]]; then
    VPIP=("$STACK/venv/bin/python" -m pip)
    # finance-mcp-server (provides python -m finance_mcp)
    if ! "$STACK/venv/bin/python" -c "import finance_mcp" 2>/dev/null; then
        log "Installing finance-mcp-server..."
        log "  → ${VPIP[*]} install -v finance-mcp-server"
        timeout 60 "${VPIP[@]}" install -v finance-mcp-server || warn "finance-mcp-server install failed"
    fi
fi

# crypto-feargreed-mcp (not on PyPI — clone + uv run)
VENDOR_DIR="$STACK/vendor"
CFG_DIR="$VENDOR_DIR/crypto-feargreed-mcp"
if [[ ! -d "$CFG_DIR" ]]; then
    mkdir -p "$VENDOR_DIR"
    log "Cloning crypto-feargreed-mcp..."
    log "  → git clone --depth 1 https://github.com/kukapay/crypto-feargreed-mcp.git $CFG_DIR"
    timeout 30 git clone --depth 1 https://github.com/kukapay/crypto-feargreed-mcp.git "$CFG_DIR" || warn "crypto-feargreed-mcp clone failed"
else
    log "crypto-feargreed-mcp already installed"
fi

# uv/uvx (needed for reddit, arxiv, mcp-mathematics, mcp-ols)
if ! command -v uvx &>/dev/null; then
    log "Installing uv (Python package runner)..."
    log "  → curl -LsSf https://astral.sh/uv/install.sh | sh"
    timeout 30 sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh' || warn "uv install failed (uvx-based MCPs won't be available)"
fi

# ── Install signals stack (Python MCP servers) ──
# Resolve Python binary: try explicit PYTHON_VERSION first, then scan
# descending 3.14→3.10, then bare python3
_PYTHON_BIN=""
for _py in "python${PYTHON_VERSION:-}" python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
    [[ -z "$_py" || "$_py" == "python" ]] && continue
    if command -v "$_py" &>/dev/null && \
       "$_py" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
        _PYTHON_BIN="$_py"; break
    fi
done

if [[ -d "$STACK/src" ]] && [[ ! -d "$STACK/venv" ]]; then
    if [[ -z "$_PYTHON_BIN" ]]; then
        warn "Python 3.10+ not found — augur MCPs won't be available"
    else
        log "Setting up signals stack Python environment..."
        cd "$STACK"
        log "Creating Python venv with $_PYTHON_BIN..."
        log "  → $_PYTHON_BIN -m venv --without-pip venv"
        "$_PYTHON_BIN" -m venv --without-pip venv
        log "Bootstrapping pip inside venv..."
        log "  → venv/bin/python -m ensurepip"
        # Redirect stdin to /dev/null for all pip/ensurepip commands —
        # when running via `curl | bash`, inherited stdin is the curl pipe
        # and pip can consume bytes meant for bash or block on the pipe.
        venv/bin/python -m ensurepip </dev/null
        log "Venv created. Checking pip version..."
        _pip_err=$(mktemp)
        _pip_ver=$(timeout 30 venv/bin/python -m pip --version </dev/null 2>"$_pip_err" | awk '{print $2}' | cut -d. -f1)
        if [[ -s "$_pip_err" ]]; then warn "pip stderr: $(cat "$_pip_err")"; fi
        rm -f "$_pip_err"
        if (( _pip_ver >= 22 )); then
            log "pip $_pip_ver is recent enough (>=22), skipping upgrade"
        else
            log "pip $_pip_ver < 22, upgrading..."
            log "  → venv/bin/python -m pip install -v --upgrade pip"
            venv/bin/python -m pip install -v --upgrade pip </dev/null
        fi
        log "Installing Python requirements (this may take a few minutes)..."
        log "  → venv/bin/python -m pip install -v --prefer-binary -r requirements.txt"
        venv/bin/python -m pip install -v --prefer-binary \
            -r requirements.txt </dev/null
        cd - >/dev/null
        log "Signals stack ready"
    fi
elif [[ -d "$STACK/venv" ]]; then
    log "Signals stack already set up"
else
    warn "Signals stack not found at $STACK — augur MCPs won't be available"
    warn "Clone with: git clone https://github.com/${GH_USER:-ManuelKugelmann}/${GH_REPO:-Augur}.git $STACK"
fi

# ── First install ───────────────────────────
if [[ "$MODE" == "install" ]]; then
    # Generate .env from example (source from mcps repo, not the bundle)
    if [[ ! -f "$APP/.env" ]]; then
        _ENV_SRC="$STACK/augur-uberspace/config/.env.example"
        if [[ -f "$_ENV_SRC" ]]; then
            cp "$_ENV_SRC" "$APP/.env"
        elif [[ -f "$APP/.env.example" ]]; then
            cp "$APP/.env.example" "$APP/.env"
        else
            die ".env.example not found — cannot generate .env"
        fi
        # Generate crypto keys
        CREDS_KEY=$(openssl rand -hex 16)
        CREDS_IV=$(openssl rand -hex 8)
        JWT_SECRET=$(openssl rand -hex 32)
        JWT_REFRESH=$(openssl rand -hex 32)

        sed -i "s|^CREDS_KEY=.*|CREDS_KEY=$CREDS_KEY|" "$APP/.env"
        sed -i "s|^CREDS_IV=.*|CREDS_IV=$CREDS_IV|" "$APP/.env"
        sed -i "s|^JWT_SECRET=.*|JWT_SECRET=$JWT_SECRET|" "$APP/.env"
        sed -i "s|^JWT_REFRESH_SECRET=.*|JWT_REFRESH_SECRET=$JWT_REFRESH|" "$APP/.env"

        # Disable search/meili
        if ! grep -q "^SEARCH=" "$APP/.env"; then
            echo "SEARCH=false" >> "$APP/.env"
        else
            sed -i "s|^SEARCH=.*|SEARCH=false|" "$APP/.env"
        fi

        # Disable RAG API (no Docker/vector DB on Uberspace)
        if ! grep -q "^RAG_API_URL=" "$APP/.env"; then
            echo "RAG_API_URL=" >> "$APP/.env"
        fi

        log "Generated crypto keys in .env"
    fi

    # ── Auto-derive MONGO_URI_SIGNALS in signals stack .env ──
    # If the user set MONGO_URI in the LibreChat .env, derive the signals
    # database URI automatically (same cluster, different database name).
    if [[ -f "$STACK/.env" ]] && [[ -f "$APP/.env" ]]; then
        LC_MONGO=$(grep "^MONGO_URI=" "$APP/.env" | head -1 | cut -d= -f2-)
        SIGNALS_MONGO=$(grep "^MONGO_URI_SIGNALS=" "$STACK/.env" | head -1 | cut -d= -f2-)
        # Only derive if LibreChat has a real URI and signals doesn't
        if [[ -n "$LC_MONGO" ]] && [[ "$LC_MONGO" != *"user:password"* ]] && \
           { [[ -z "$SIGNALS_MONGO" ]] || [[ "$SIGNALS_MONGO" == *"user:password"* ]]; }; then
            # Replace database name: mongodb+srv://user:pass@host/LibreChat?params → .../signals?params
            DERIVED=$(echo "$LC_MONGO" | sed -E 's|(/[^/?]+)(\?)|/signals\2|; t; s|(/[^/?]+)$|/signals|')
            # If no database name in URI, just append /signals
            if [[ "$DERIVED" == "$LC_MONGO" ]]; then
                if [[ "$LC_MONGO" == *"?"* ]]; then
                    DERIVED="${LC_MONGO%%\?*}/signals?${LC_MONGO#*\?}"
                else
                    DERIVED="${LC_MONGO}/signals"
                fi
            fi
            sed -i "s|^MONGO_URI_SIGNALS=.*|MONGO_URI_SIGNALS=$DERIVED|" "$STACK/.env"
            log "Auto-derived MONGO_URI_SIGNALS from MONGO_URI (database: signals)"
        fi
    fi

    # Register librechat systemd service
    log "Registering librechat service..."
    SVC_DIR="$HOME/.config/systemd/user"
    mkdir -p "$SVC_DIR"
    cat > "$SVC_DIR/librechat.service" <<EOF
[Install]
WantedBy=default.target

[Service]
WorkingDirectory=${APP}
Environment=NODE_ENV=production
ExecStart=node --max-old-space-size=1024 api/server/index.js
Restart=always
RestartSec=60
EOF
    systemctl --user daemon-reload
    systemctl --user enable librechat || true

    # Web backend
    log "  → web backend / → port $PORT"
    _web_backend / "$PORT" || warn "Failed to set web backend on port $PORT"

    # Install ops shortcut (atomic: temp+mv to avoid overwriting running script)
    mkdir -p "$HOME/bin"
    cp "$STACK/Augur.sh" "$HOME/bin/augur.tmp" 2>/dev/null \
        && mv -f "$HOME/bin/augur.tmp" "$HOME/bin/augur" 2>/dev/null || true
    chmod +x "$HOME/bin/augur" 2>/dev/null || true
    ln -sf "$HOME/bin/augur" "$HOME/bin/Augur" 2>/dev/null || true

    log "Installed ${VER}"
else
    # ── Update: restart ─────────────────────
    log "  → starting librechat service"
    _svc_start_lc
    log "Updated to ${VER} — service restarted"
fi

echo "$VER" > "$APP/.version"
