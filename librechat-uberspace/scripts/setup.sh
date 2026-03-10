#!/bin/bash
# LibreChat Lite — install or update on Uberspace
# Called by TradeAssistant.sh (_lc_download_and_setup) or directly: bash setup.sh <app-dir> <version>
set -euo pipefail

# ── Load central config ──
for conf in "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/deploy.conf" \
            "$HOME/assist/deploy.conf"; do
    [[ -f "$conf" ]] && { source "$conf"; break; }
done

SRC="${1:?Usage: setup.sh <app-dir> <version>}"
VER="${2:-unknown}"
APP="${APP_DIR:-$HOME/LibreChat}"
BAK="${APP}.prev"
STACK="${STACK_DIR:-$HOME/assist}"
PORT="${LC_PORT:-3080}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
die()  { echo -e "${RED}✗${NC} $1" >&2; exit 1; }

# ── Platform detection ──
_is_u8() { [[ -f /etc/arch-release ]]; }

_svc_stop_lc() {
    if _is_u8; then
        systemctl --user stop librechat 2>/dev/null || true
    else
        supervisorctl stop librechat 2>/dev/null || true
    fi
}
_svc_start_lc() {
    if _is_u8; then
        systemctl --user start librechat 2>/dev/null || true
    else
        supervisorctl start librechat 2>/dev/null || supervisorctl restart librechat 2>/dev/null || true
    fi
}
_web_backend() {
    local path="$1" port="$2"
    if _is_u8; then
        uberspace web backend add "$path" port "$port" --force 2>/dev/null
    else
        uberspace web backend set "$path" --http --port "$port" 2>/dev/null
    fi
}

# Dirs that survive updates
PERSIST=(uploads logs images)

# ── Pre-flight ──────────────────────────────
command -v node &>/dev/null || die "Node.js not found. On U7: uberspace tools version use node ${NODE_VERSION:-22}. On U8: node is system-provided."
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

# ── Stop service before swap ────────────────
if [[ "$MODE" == "update" ]]; then
    _svc_stop_lc
    sleep 2

    # Preserve .env and persistent dirs
    [[ -f "$APP/.env" ]] && cp "$APP/.env" "$SRC/.env"
    [[ -f "$APP/librechat.yaml" ]] && cp "$APP/librechat.yaml" "$SRC/librechat.yaml"
    for d in "${PERSIST[@]}"; do
        [[ -d "$APP/$d" ]] && { rm -rf "$SRC/$d"; mv "$APP/$d" "$SRC/$d"; }
    done
fi

# ── Atomic swap ─────────────────────────────
rm -rf "$BAK"
[[ -d "$APP" ]] && mv "$APP" "$BAK"
mv "$SRC" "$APP"

for d in "${PERSIST[@]}"; do mkdir -p "$APP/$d"; done

# ── Verify LibreChat app code is present ────
# The release bundle must include pre-built LibreChat (built in CI).
if [[ ! -f "$APP/api/server/index.js" ]]; then
    # Rollback: restore previous version if it existed
    rm -rf "$APP"
    [[ -d "$BAK" ]] && mv "$BAK" "$APP"
    die "LibreChat app code missing from bundle. Use a release built with CI (git tag + push)."
fi

# ── Copy default config from mcps repo if missing ──
# The LibreChat bundle is vanilla — config lives in the mcps repo.
_LC_YAML_SRC="$STACK/librechat-uberspace/config/librechat.yaml"
if [[ ! -f "$APP/librechat.yaml" ]] && [[ -f "$_LC_YAML_SRC" ]]; then
    cp "$_LC_YAML_SRC" "$APP/librechat.yaml"
    sed -i "s|__HOME__|$HOME|g" "$APP/librechat.yaml"
    log "Copied default librechat.yaml from mcps repo (paths adjusted to $HOME)"
elif [[ ! -f "$APP/librechat.yaml" ]]; then
    warn "librechat.yaml not found in mcps repo — configure manually"
fi

# No additional MCP npm packages needed — trading server is Python-only.

# ── Install external MCP dependencies ─────────────
# RSS MCP (Node, runs via node_modules)
if [[ ! -d "$STACK/node_modules/rss-mcp" ]]; then
    log "Installing rss-mcp..."
    cd "$STACK"
    timeout 60 npm install rss-mcp 2>/dev/null || warn "rss-mcp install failed (RSS feed MCP won't be available)"
    cd - >/dev/null
else
    log "rss-mcp already installed"
fi

# Python MCPs installed into signals stack venv
if [[ -d "$STACK/venv" ]]; then
    VPIP="$STACK/venv/bin/pip"
    # finance-mcp-server (provides python -m finance_mcp)
    if ! "$STACK/venv/bin/python" -c "import finance_mcp" 2>/dev/null; then
        log "Installing finance-mcp-server..."
        timeout 60 "$VPIP" install finance-mcp-server || warn "finance-mcp-server install failed"
    fi
fi

# crypto-feargreed-mcp (not on PyPI — clone + uv run)
VENDOR_DIR="$STACK/vendor"
CFG_DIR="$VENDOR_DIR/crypto-feargreed-mcp"
if [[ ! -d "$CFG_DIR" ]]; then
    mkdir -p "$VENDOR_DIR"
    log "Cloning crypto-feargreed-mcp..."
    timeout 30 git clone -q --depth 1 https://github.com/kukapay/crypto-feargreed-mcp.git "$CFG_DIR" || warn "crypto-feargreed-mcp clone failed"
else
    log "crypto-feargreed-mcp already installed"
fi

# uv/uvx (needed for reddit, arxiv, mcp-mathematics, mcp-ols)
if ! command -v uvx &>/dev/null; then
    log "Installing uv (Python package runner)..."
    timeout 30 sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh' 2>/dev/null || warn "uv install failed (uvx-based MCPs won't be available)"
fi

# ── Install signals stack (Python MCP servers) ──
# Resolve Python binary: try explicit PYTHON_VERSION first, then scan
# descending 3.14→3.10, then bare python3 (works on U7 + U8 + generic Linux)
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
        warn "Python 3.10+ not found — trading MCPs won't be available"
    else
        log "Setting up signals stack Python environment..."
        cd "$STACK"
        log "Creating Python venv with $_PYTHON_BIN..."
        "$_PYTHON_BIN" -m venv venv
        log "Venv created. Upgrading pip..."
        timeout 60 venv/bin/pip install --upgrade pip
        log "Installing requirements (this may take a few minutes)..."
        _pip_constraint=""
        if ! _is_u8; then
            _pip_constraint=$(mktemp)
            echo 'pandas<3' > "$_pip_constraint"
        fi
        timeout 180 venv/bin/pip install --prefer-binary \
            ${_pip_constraint:+-c "$_pip_constraint"} \
            -r requirements.txt
        [[ -n "$_pip_constraint" ]] && rm -f "$_pip_constraint"
        cd - >/dev/null
        log "Signals stack ready"
    fi
elif [[ -d "$STACK/venv" ]]; then
    log "Signals stack already set up"
else
    warn "Signals stack not found at $STACK — trading MCPs won't be available"
    warn "Clone with: git clone https://github.com/${GH_USER:-ManuelKugelmann}/${GH_REPO:-TradingAssistant}.git $STACK"
fi

# ── First install ───────────────────────────
if [[ "$MODE" == "install" ]]; then
    # Generate .env from example (source from mcps repo, not the bundle)
    if [[ ! -f "$APP/.env" ]]; then
        _ENV_SRC="$STACK/librechat-uberspace/config/.env.example"
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
            # Also set in LibreChat .env for the trading service
            if ! grep -q "^MONGO_URI_SIGNALS=" "$APP/.env"; then
                echo "MONGO_URI_SIGNALS=$DERIVED" >> "$APP/.env"
            else
                sed -i "s|^MONGO_URI_SIGNALS=.*|MONGO_URI_SIGNALS=$DERIVED|" "$APP/.env"
            fi
            log "Auto-derived MONGO_URI_SIGNALS from MONGO_URI (database: signals)"
        fi
    fi

    # Register librechat service (U7: supervisord, U8: systemd)
    if _is_u8; then
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
        systemctl --user enable librechat 2>/dev/null || true
    else
        SVC="$HOME/etc/services.d/librechat.ini"
        mkdir -p "$(dirname "$SVC")"
        cat > "$SVC" <<EOF
[program:librechat]
directory=${APP}
command=node --max-old-space-size=1024 api/server/index.js
environment=NODE_ENV=production
autostart=true
autorestart=true
startsecs=60
stopsignal=TERM
stopwaitsecs=10
EOF
        supervisorctl reread 2>/dev/null
        supervisorctl add librechat 2>/dev/null || true
    fi

    # Web backend
    _web_backend / "$PORT" || warn "Failed to set web backend on port $PORT"

    # Install ops shortcut (from mcps repo, not the bundle)
    mkdir -p "$HOME/bin"
    cp "$STACK/librechat-uberspace/scripts/TradeAssistant.sh" "$HOME/bin/ta" 2>/dev/null || true
    chmod +x "$HOME/bin/ta" 2>/dev/null || true
    ln -sf "$HOME/bin/ta" "$HOME/bin/TradeAssistant" 2>/dev/null || true

    echo ""
    log "Installed ${VER}"
    echo ""
    echo -e "${CYAN}Next steps:${NC}"
    echo ""
    echo -e "  ${YELLOW}1.${NC} Configure LibreChat:"
    echo "     nano $APP/.env"
    echo ""
    echo "     Required:"
    echo "       MONGO_URI=mongodb+srv://user:pass@cluster.mongodb.net/LibreChat"
    echo "       MONGO_URI_SIGNALS=mongodb+srv://user:pass@cluster.mongodb.net/signals"
    echo "       At least one LLM key (many free tiers — see docs/llm-keys.md)"
    echo ""
    echo -e "  ${YELLOW}2.${NC} Configure MCP servers (optional, defaults are fine):"
    echo "     nano $APP/librechat.yaml"
    echo ""
    echo -e "  ${YELLOW}3.${NC} Start (auto-restarts on reboot):"
    if _is_u8; then
        echo "     systemctl --user start librechat"
    else
        echo "     supervisorctl start librechat"
    fi
    echo ""
    echo -e "  ${YELLOW}4.${NC} Access:"
    echo "     https://${UBER_HOST:-$(hostname -f 2>/dev/null || echo 'YOUR_USER.uber.space')}"
    echo ""
else
    # ── Update: restart ─────────────────────
    _svc_start_lc
    log "Updated to ${VER} — service restarted"
fi

echo "$VER" > "$APP/.version"
