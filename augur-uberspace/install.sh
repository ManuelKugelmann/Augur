#!/bin/bash
# Augur installer — self-contained, works via curl|bash
#
# Fresh install:
#   curl -sL "https://raw.githubusercontent.com/ManuelKugelmann/Augur/main/augur-uberspace/install.sh?$(date +%s)" | bash
#
# Re-run (idempotent):
#   augur install
#
# Also callable from Augur.sh (augur install delegates here).

# Wrap in _main() so `curl | bash` must receive the full script before
# executing anything (prevents partial-execution on slow/interrupted downloads).
_main() {
set -euo pipefail

# ── Abort trap ──
_abort() {
    trap - INT TERM
    echo -e "\n\033[0;31m✗\033[0m Aborted." >&2
    kill 0 2>/dev/null || true
    exit 130
}
trap '_abort' INT TERM

# ── Defaults ──
GH_USER="${GH_USER:-ManuelKugelmann}"
GH_REPO="${GH_REPO:-Augur}"
STACK_DIR="${STACK_DIR:-$HOME/augur}"
APP_DIR="${APP_DIR:-$HOME/LibreChat}"
LC_PORT="${LC_PORT:-3080}"
NODE_VERSION="${NODE_VERSION:-24}"
BRANCH="${BRANCH:-main}"

# ── Load config if available (re-run from cloned repo) ──
if [[ -f "$STACK_DIR/deploy.conf" ]]; then
    source "$STACK_DIR/deploy.conf"
fi

APP="${APP_DIR:-$HOME/LibreChat}"
STACK="${STACK_DIR:-$HOME/augur}"

# ── Output helpers ──
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
die()  { echo -e "${RED}✗${NC} $1" >&2; exit 1; }

# ── Service management (systemd) ──
_svc_start()   { systemctl --user start "$1"; }
_svc_stop()    { systemctl --user stop "$1"; }
_svc_restart() { systemctl --user restart "$1"; }
_svc_reload()  { systemctl --user daemon-reload || true; }
_web_backend() {
    local path="$1" port="$2"
    # Skip if already configured (avoids httpx timeout on uberspace CLI)
    local existing
    existing=$(uberspace web backend list 2>&1 || true)
    if echo "$existing" | grep -qF "$path" && echo "$existing" | grep -q "$port"; then
        log "Web backend ${path} → port ${port} already set"
        return 0
    fi
    local attempt=0 delay=2
    while (( attempt < 3 )); do
        attempt=$((attempt + 1))
        uberspace web backend add "$path" port "$port" --force && return 0
        (( attempt < 3 )) && { warn "web backend ${path} attempt ${attempt}/3 timed out, retrying in ${delay}s..."; sleep "$delay"; delay=$((delay * 2)); }
    done
    return 1
}

# ── pip helpers ──
_pip_upgrade() {
    local python="$1" min_ver=22
    log "  → $python -m pip --version"
    local ver _pip_err
    _pip_err=$(mktemp)
    ver=$(timeout 30 "$python" -m pip --version </dev/null 2>"$_pip_err" | awk '{print $2}' | cut -d. -f1)
    local rc=$?
    if [[ -s "$_pip_err" ]]; then warn "pip stderr: $(cat "$_pip_err")"; fi
    rm -f "$_pip_err"
    if (( rc == 124 )); then
        warn "pip --version timed out (30s) — pip is slow but likely fine, skipping upgrade"
        return 0
    fi
    if (( rc != 0 )); then
        warn "pip --version exited $rc"; return 1
    fi
    if [[ -z "$ver" ]]; then
        warn "pip --version returned empty output"; return 1
    fi
    if (( ver >= min_ver )); then
        log "pip $ver is recent enough (>=$min_ver), skipping upgrade"
        return 0
    fi
    log "pip $ver < $min_ver, upgrading..."
    log "  → $python -m pip install -v --upgrade pip"
    "$python" -m pip install -v --upgrade pip </dev/null
}

_pip_install() {
    local python="$1" req="$2"
    log "  → $python -m pip install -v --only-binary numpy,pandas --prefer-binary -r $req ${*:3}"
    "$python" -m pip install -v --only-binary numpy,pandas --prefer-binary -r "$req" "${@:3}" </dev/null
}

# ── HTTP helpers ──
gh_curl() { curl -sf --connect-timeout 10 --max-time 30 "$@"; }

_download() {
    local url="$1" out="$2" desc="${3:-file}"
    local retries=4 attempt=0 delay=2 rc=0

    local size_bytes=""
    size_bytes=$(curl -sfI -L --connect-timeout 5 --max-time 10 "$url" 2>/dev/null | grep -i '^content-length:' | tail -1 | tr -d '[:space:]' | cut -d: -f2 || true)
    if [[ -n "$size_bytes" && "$size_bytes" -gt 0 ]] 2>/dev/null; then
        local size_mb
        size_mb=$(awk "BEGIN {printf \"%.1f\", $size_bytes / 1048576}")
        echo -e "  ${CYAN}↓${NC} ${desc} (${size_mb} MB)"
    else
        echo -e "  ${CYAN}↓${NC} ${desc}"
    fi
    echo -e "  ${CYAN}  URL:${NC} ${url}"

    while (( attempt < retries )); do
        attempt=$((attempt + 1))
        rc=0
        curl -fL --progress-bar --connect-timeout 15 --max-time 600 -o "$out" "$url" || rc=$?
        if [[ $rc -eq 0 && -s "$out" ]]; then
            local got_mb
            got_mb=$(awk "BEGIN {printf \"%.1f\", $(stat -c%s "$out" 2>/dev/null || stat -f%z "$out" 2>/dev/null || echo 0) / 1048576}")
            echo -e "  ${GREEN}✓${NC} Downloaded ${got_mb} MB"
            return 0
        fi
        if (( attempt < retries )); then
            warn "Download attempt ${attempt}/${retries} failed, retrying in ${delay}s..."
            sleep "$delay"
            delay=$((delay * 2))
        fi
    done
    die "Download failed after ${retries} attempts: ${desc}"
}

_resolve_bundle_url() {
    _BUNDLE_URL="" _BUNDLE_TAG=""
    local json="" api_url=""
    if [[ -z "${RELEASE_TAG:-}" ]]; then
        api_url="https://api.github.com/repos/${GH_USER}/${GH_REPO}/releases/latest"
        log "Checking latest release: ${api_url}"
        json=$(gh_curl "$api_url" 2>/dev/null) || json=""
    elif [[ "${RELEASE_TAG}" == "prerelease" ]]; then
        api_url="https://api.github.com/repos/${GH_USER}/${GH_REPO}/releases?per_page=1"
        log "Checking prereleases: ${api_url}"
        json=$(gh_curl "$api_url" 2>/dev/null) || json=""
        json=$(echo "$json" | sed -n 's/^\[//;s/\]$//;p' | head -1)
    else
        api_url="https://api.github.com/repos/${GH_USER}/${GH_REPO}/releases/tags/${RELEASE_TAG}"
        log "Checking release tag: ${api_url}"
        json=$(gh_curl "$api_url" 2>/dev/null) || json=""
    fi
    if [[ -n "$json" ]]; then
        _BUNDLE_URL=$(echo "$json" | grep -oE '"browser_download_url":\s*"[^"]*librechat-(bundle|build)\.tar\.gz"' | head -1 | grep -oE '(https?|file)://[^"]+' || true)
        _BUNDLE_TAG=$(echo "$json" | grep -o '"tag_name":[^"]*"[^"]*"' | cut -d'"' -f4 || true)
    fi
    if [[ -z "$_BUNDLE_URL" && -z "${RELEASE_TAG:-}" ]]; then
        api_url="https://api.github.com/repos/${GH_USER}/${GH_REPO}/releases/tags/librechat-build"
        log "No bundle in latest release, trying: ${api_url}"
        json=$(gh_curl "$api_url" 2>/dev/null) || json=""
        if [[ -n "$json" ]]; then
            _BUNDLE_URL=$(echo "$json" | grep -oE '"browser_download_url":\s*"[^"]*librechat-(bundle|build)\.tar\.gz"' | head -1 | grep -oE '(https?|file)://[^"]+' || true)
            _BUNDLE_TAG=$(echo "$json" | grep -o '"tag_name":[^"]*"[^"]*"' | cut -d'"' -f4 || true)
        fi
    fi
    [[ -n "$_BUNDLE_URL" ]] && log "Found bundle: ${_BUNDLE_URL} (tag: ${_BUNDLE_TAG})"
}

_resolve_mcp_nodes_url() {
    _MCP_NODES_URL="" _MCP_NODES_TAG=""
    local json="" api_url=""
    local tag="${MCP_NODES_TAG:-mcp-nodes-build}"

    api_url="https://api.github.com/repos/${GH_USER}/${GH_REPO}/releases/tags/${tag}"
    log "Checking MCP nodes release: ${api_url}"
    json=$(gh_curl "$api_url" 2>/dev/null) || json=""

    if [[ -n "$json" ]]; then
        _MCP_NODES_URL=$(echo "$json" | grep -oE '"browser_download_url":\s*"[^"]*mcp-nodes-build\.tar\.gz"' | head -1 | grep -oE '(https?|file)://[^"]+' || true)
        _MCP_NODES_TAG=$(echo "$json" | grep -o '"tag_name":[^"]*"[^"]*"' | cut -d'"' -f4 || true)
    fi

    [[ -n "$_MCP_NODES_URL" ]] && log "Found MCP nodes bundle: ${_MCP_NODES_URL} (tag: ${_MCP_NODES_TAG})"
}

_mcp_nodes_download_and_setup() {
    local skip_current=false
    [[ "${1:-}" == "--skip-if-current" ]] && skip_current=true

    _resolve_mcp_nodes_url
    [[ -z "$_MCP_NODES_URL" ]] && return 1

    local mcp_dir="$STACK/mcp-nodes"

    if [[ "$skip_current" == true && -f "$mcp_dir/.version" ]]; then
        local installed_ver=""
        installed_ver=$(head -1 "$mcp_dir/.version")
        if [[ -n "$installed_ver" && -n "$_MCP_NODES_TAG" ]]; then
            local tag_ver="${_MCP_NODES_TAG#mcp-nodes-v}"
            if [[ "$installed_ver" == "$tag_ver" || "$installed_ver" == "$_MCP_NODES_TAG" ]]; then
                log "MCP nodes already up-to-date (${installed_ver})"
                return 0
            fi
            log "Updating MCP nodes ${installed_ver} → ${_MCP_NODES_TAG}..."
        fi
    fi

    local mcp_tmp
    mcp_tmp=$(mktemp -d)
    log "Downloading MCP nodes bundle..."
    _download "$_MCP_NODES_URL" "$mcp_tmp/mcp-nodes.tar.gz" "MCP nodes bundle${_MCP_NODES_TAG:+ ($_MCP_NODES_TAG)}"

    log "Extracting MCP nodes bundle..."
    mkdir -p "$mcp_dir"
    rm -rf "$mcp_dir/node_modules" "$mcp_dir/.bin"
    tar xzf "$mcp_tmp/mcp-nodes.tar.gz" -C "$mcp_dir"
    rm -rf "$mcp_tmp"

    log "MCP nodes bundle installed ($(head -1 "$mcp_dir/.version" 2>/dev/null || echo 'unknown'))"
    return 0
}

_lc_download_and_setup() {
    local skip_current=false
    [[ "${1:-}" == "--skip-if-current" ]] && skip_current=true
    _resolve_bundle_url
    [[ -z "$_BUNDLE_URL" ]] && return 1
    if [[ "$skip_current" == true ]]; then
        local installed_ver=""
        [[ -f "$APP/.version" ]] && installed_ver=$(cat "$APP/.version")
        if [[ -n "$installed_ver" && -n "$_BUNDLE_TAG" ]]; then
            local tag_ver="${_BUNDLE_TAG#v}"
            if [[ "$installed_ver" == "$tag_ver" || "$installed_ver" == "$_BUNDLE_TAG" ]]; then
                log "LibreChat already up-to-date (${installed_ver})"
                return 0
            fi
            log "Updating LibreChat ${installed_ver} → ${_BUNDLE_TAG}..."
        fi
    fi
    local lc_tmp
    lc_tmp=$(mktemp -d -p "$HOME" .lc-install.XXXXXX)
    # shellcheck disable=SC2064
    trap "rm -rf '$lc_tmp'" EXIT
    log "Downloading LibreChat release..."
    _download "$_BUNDLE_URL" "$lc_tmp/bundle.tar.gz" "LibreChat bundle${_BUNDLE_TAG:+ ($_BUNDLE_TAG)}"
    local bundle_size
    bundle_size=$(stat -c%s "$lc_tmp/bundle.tar.gz" 2>/dev/null || stat -f%z "$lc_tmp/bundle.tar.gz" 2>/dev/null || echo "")
    local size_info=""
    if [[ -n "$bundle_size" && "$bundle_size" -gt 0 ]] 2>/dev/null; then
        size_info=" ($(awk "BEGIN {printf \"%.1f\", $bundle_size / 1048576}") MB)"
    fi
    mkdir -p "$lc_tmp/app"
    log "Extracting bundle${size_info}..."
    if command -v pigz &>/dev/null; then
        log "  → tar -I pigz -xf $lc_tmp/bundle.tar.gz -C $lc_tmp/app"
        tar -I pigz -xf "$lc_tmp/bundle.tar.gz" -C "$lc_tmp/app" -v
    else
        log "  → tar xzf $lc_tmp/bundle.tar.gz -C $lc_tmp/app"
        tar xzf "$lc_tmp/bundle.tar.gz" -C "$lc_tmp/app" -v
    fi
    log "Extraction complete"
    local bundle_ver=""
    [[ -f "$lc_tmp/app/.version" ]] && bundle_ver=$(cat "$lc_tmp/app/.version")
    [[ -z "$bundle_ver" ]] && bundle_ver="${_BUNDLE_TAG:-unknown}"
    log "LibreChat version: ${bundle_ver}"
    log "Running setup..."
    log "  → bash $STACK/augur-uberspace/scripts/setup.sh $lc_tmp/app $bundle_ver"
    bash "$STACK/augur-uberspace/scripts/setup.sh" "$lc_tmp/app" "$bundle_ver"
    return 0
}

# ═══════════════════════════════════════════════
#  install — full install/update (idempotent)
# ═══════════════════════════════════════════════
_do_install() {
    local NEED_STACK_ENV=false
    local NEED_APP_ENV=false

    # ── Resolve version for header ─
    local _hdr_sha="" _hdr_date=""
    if [[ -d "$STACK/.git" ]]; then
        _hdr_sha=$(git -C "$STACK" rev-parse --short HEAD 2>/dev/null || true)
        _hdr_date=$(git -C "$STACK" log -1 --format='%ci' 2>/dev/null || true)
    fi
    if [[ -z "$_hdr_sha" ]]; then
        local _api_json
        _api_json=$(curl -sf --connect-timeout 5 --max-time 10 "https://api.github.com/repos/${GH_USER}/${GH_REPO}/commits/${BRANCH}" 2>/dev/null || true)
        if [[ -n "$_api_json" ]]; then
            _hdr_sha=$(echo "$_api_json" | grep -o '"sha": *"[^"]*"' | head -1 | cut -d'"' -f4 || true)
            _hdr_sha="${_hdr_sha:0:7}"
            _hdr_date=$(echo "$_api_json" | grep -o '"date": *"[^"]*"' | tail -1 | cut -d'"' -f4 || true)
        fi
    fi

    echo -e "${CYAN}══════════════════════════════════════════${NC}"
    echo -e "${CYAN} Augur + LibreChat → Uberspace ${NC}"
    [[ -n "$_hdr_sha" ]] && echo -e "${CYAN} ${_hdr_sha}  ${_hdr_date} ${NC}"
    echo -e "${CYAN}══════════════════════════════════════════${NC}"
    echo ""

    # ── 1. Node.js ──
    command -v node &>/dev/null || die "Node.js not available"
    log "Node.js $(node -v) (system-provided)"

    # ── 2. Clone or update repo ──
    if [[ -d "$STACK/.git" ]]; then
        log "Repo exists at $STACK, pulling latest..."
        log "  → git -C $STACK pull --ff-only origin $BRANCH"
        git -C "$STACK" pull --ff-only origin "$BRANCH" || \
            { log "  → git -C $STACK fetch origin $BRANCH && git reset --hard origin/$BRANCH"
              git -C "$STACK" fetch origin "$BRANCH" && \
              git -C "$STACK" reset --hard "origin/$BRANCH"; }
        log "Repo updated"
    else
        log "Cloning repo..."
        log "  → git clone -b $BRANCH https://github.com/${GH_USER}/${GH_REPO}.git $STACK"
        git clone -b "$BRANCH" "https://github.com/${GH_USER}/${GH_REPO}.git" "$STACK"
        log "Cloned → $STACK"
    fi

    _INSTALL_SHA=$(git -C "$STACK" rev-parse --short HEAD 2>/dev/null || echo "unknown")
    _INSTALL_COMMIT_DATE=$(git -C "$STACK" log -1 --format='%ci' 2>/dev/null || echo "unknown")
    log "Version: ${_INSTALL_SHA} (${_INSTALL_COMMIT_DATE})"

    [[ -f "$STACK/deploy.conf" ]] && source "$STACK/deploy.conf"

    # ── 3. Python venv ──
    PYTHON_BIN=""
    for _py in "python${PYTHON_VERSION:-}" python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
        [[ -z "$_py" || "$_py" == "python" ]] && continue
        if command -v "$_py" &>/dev/null && \
           "$_py" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
            PYTHON_BIN="$_py"; break
        fi
    done
    [[ -z "$PYTHON_BIN" ]] && die "Python 3.10+ not found. Check: python3 --version"
    _pyver=$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    log "Using $PYTHON_BIN (Python $_pyver)"

    if [[ -d "$STACK/venv" ]]; then
        # Detect stale venv: if the python binary is missing or broken, recreate
        local _venv_check
        if ! _venv_check=$(timeout 10 "$STACK/venv/bin/python" -c 'import sys; print(sys.version)' </dev/null 2>&1); then
            warn "Venv python is broken or stale. Output: $_venv_check"
            warn "Recreating venv..."
            rm -rf "$STACK/venv"
        else
            log "Python venv exists, checking pip..."
            if ! _pip_upgrade "$STACK/venv/bin/python"; then
                warn "pip check failed, recreating venv..."
                rm -rf "$STACK/venv"
            fi
        fi
    fi
    if [[ ! -d "$STACK/venv" ]]; then
        log "Creating Python venv..."
        log "  → $PYTHON_BIN -m venv --without-pip $STACK/venv"
        "$PYTHON_BIN" -m venv --without-pip "$STACK/venv"
        log "Bootstrapping pip inside venv..."
        log "  → $STACK/venv/bin/python -m ensurepip"
        "$STACK/venv/bin/python" -m ensurepip </dev/null \
            || die "ensurepip failed"
    fi
    local _req_hash _cached_hash=""
    _req_hash=$(sha256sum "$STACK/requirements.txt" 2>/dev/null | cut -d' ' -f1 || true)
    [[ -f "$STACK/venv/.req_hash" ]] && _cached_hash=$(cat "$STACK/venv/.req_hash")
    if [[ -n "$_req_hash" && "$_req_hash" == "$_cached_hash" ]]; then
        log "Python requirements unchanged, skipping pip install"
    else
        log "Installing Python requirements..."
        _pip_install "$STACK/venv/bin/python" "$STACK/requirements.txt" \
            || die "pip install requirements failed"
        echo "$_req_hash" > "$STACK/venv/.req_hash"
    fi
    log "Python venv ready"

    # ── 4. Signals stack .env ──
    if [[ ! -f "$STACK/.env" ]]; then
        cp "$STACK/.env.example" "$STACK/.env"
        NEED_STACK_ENV=true
        log "Created $STACK/.env (needs configuration)"
    else
        log "Signals .env already exists"
    fi

    # ── 5. Register services ──
    log "Registering services..."
    mkdir -p ~/.config/systemd/user ~/logs
    cat > ~/.config/systemd/user/trading.service << SVCEOF
[Install]
WantedBy=default.target

[Service]
WorkingDirectory=${STACK}
EnvironmentFile=${STACK}/.env
Environment=MCP_TRANSPORT=http
Environment=MCP_PORT=8071
ExecStart=${STACK}/venv/bin/python src/servers/combined_server.py
Restart=always
RestartSec=10
SVCEOF
    cat > ~/.config/systemd/user/charts.service << SVCEOF
[Install]
WantedBy=default.target

[Service]
WorkingDirectory=${STACK}
ExecStart=${STACK}/venv/bin/python src/store/charts.py
Restart=always
RestartSec=60
SVCEOF
    systemctl --user daemon-reload
    systemctl --user enable trading || true
    systemctl --user enable charts || true
    _web_backend /charts 8066 || warn "Failed to set /charts web backend"
    log "Services registered (trading, charts)"

    # ── 6. LibreChat ──
    local NEED_LC_SETUP=false
    local _pre_ver=""
    [[ -f "$APP/.version" ]] && _pre_ver=$(cat "$APP/.version")
    [[ ! -f "$APP/.env" ]] && NEED_APP_ENV=true

    if ! _lc_download_and_setup --skip-if-current; then
        die "No prebuilt LibreChat release found. Create one via: Actions → Release LibreChat Bundle → Run workflow (or: git tag v0.x.0 && git push --tags)"
    fi

    local _post_ver=""
    [[ -f "$APP/.version" ]] && _post_ver=$(cat "$APP/.version")
    if [[ "$_pre_ver" != "$_post_ver" ]] || [[ -z "$_pre_ver" ]]; then
        NEED_LC_SETUP=true
    fi

    if [[ "$NEED_LC_SETUP" == false ]]; then
        local SVC="$HOME/.config/systemd/user/librechat.service"
        if [[ ! -f "$SVC" ]]; then
            mkdir -p "$(dirname "$SVC")"
            cat > "$SVC" <<SVCEOF
[Install]
WantedBy=default.target

[Service]
WorkingDirectory=${APP}
Environment=NODE_ENV=production
ExecStart=node --max-old-space-size=1024 api/server/index.js
Restart=always
RestartSec=60
SVCEOF
            systemctl --user daemon-reload
            systemctl --user enable librechat || true
            log "Systemd service re-registered"
        fi
        _web_backend / "${LC_PORT}" || warn "Failed to set web backend on port ${LC_PORT}"
    fi

    # ── 6.5. MCP Node servers (prebuilt bundle) ──
    log "Checking MCP Node servers bundle..."
    if ! _mcp_nodes_download_and_setup --skip-if-current; then
        warn "MCP Node servers bundle not found — Node MCPs (rss, prediction-markets, hackernews) won't be available"
        warn "Build one via: Actions → Build MCP Nodes → Run workflow"
    fi

    # ── 7. Install augur shortcut ──
    mkdir -p "$HOME/bin"
    cp "$STACK/Augur.sh" "$HOME/bin/augur" 2>/dev/null || true
    chmod +x "$HOME/bin/augur" 2>/dev/null || true
    ln -sf "$HOME/bin/augur" "$HOME/bin/Augur" 2>/dev/null || true

    if [[ -f "$HOME/.bashrc" ]] && ! grep -q 'export PATH="$HOME/bin:$PATH"' "$HOME/.bashrc" 2>/dev/null; then
        echo '' >> "$HOME/.bashrc"
        echo '# Added by Augur installer' >> "$HOME/.bashrc"
        echo 'export PATH="$HOME/bin:$PATH"' >> "$HOME/.bashrc"
        log "Added ~/bin to PATH in .bashrc"
    elif [[ ! -f "$HOME/.bashrc" ]]; then
        echo '# Added by Augur installer' > "$HOME/.bashrc"
        echo 'export PATH="$HOME/bin:$PATH"' >> "$HOME/.bashrc"
        log "Created .bashrc with ~/bin in PATH"
    fi

    # ── 8. Reload service manager ──
    _svc_reload

    # ── 9. Auto-seed agents ──
    if [[ -n "${AUGUR_SETUP_EMAIL:-}" ]] && [[ -n "${AUGUR_SETUP_PASSWORD:-}" ]]; then
        local LC_URL="http://localhost:${LC_PORT:-3080}"
        local LC_READY=false
        _svc_start librechat || true
        for i in $(seq 1 30); do
            if curl -sf "${LC_URL}/api/health" >/dev/null 2>&1; then
                LC_READY=true; break
            fi
            sleep 2
        done
        if [[ "$LC_READY" == true ]]; then
            log "LibreChat is ready, seeding agents..."
            log "  → $STACK/venv/bin/python $STACK/augur-uberspace/scripts/seed-agents.py --email ... --base-url $LC_URL"
            "$STACK/venv/bin/python" "$STACK/augur-uberspace/scripts/seed-agents.py" \
                --email "$AUGUR_SETUP_EMAIL" --password "$AUGUR_SETUP_PASSWORD" \
                --base-url "$LC_URL" 2>&1 || warn "Agent seeding failed (seed manually: augur agents)"
        else
            warn "LibreChat not ready after 60s — seed agents manually: augur agents <email> <password>"
        fi
    fi

    # Profile seeding happens automatically on first trading server start
    # (see combined_server.py). No need to seed during install.

    # ── 11. Bootstrap profile data via agent ──
    if [[ -n "${AUGUR_AGENTS_API_KEY:-}" ]] && [[ -n "${AUGUR_BOOTSTRAP_AGENT_ID:-}" ]]; then
        local LC_URL="http://localhost:${LC_PORT:-3080}"
        local LC_READY=false
        for i in $(seq 1 15); do
            if curl -sf "${LC_URL}/api/health" >/dev/null 2>&1; then
                LC_READY=true; break
            fi
            sleep 2
        done
        if [[ "$LC_READY" == true ]]; then
            log "Bootstrapping profile data via agent..."
            log "  → $STACK/venv/bin/python $STACK/augur-uberspace/scripts/bootstrap-data.py --base-url $LC_URL --timeseries"
            "$STACK/venv/bin/python" "$STACK/augur-uberspace/scripts/bootstrap-data.py" \
                --api-key "$AUGUR_AGENTS_API_KEY" \
                --agent-id "$AUGUR_BOOTSTRAP_AGENT_ID" \
                --base-url "$LC_URL" \
                --timeseries 2>&1 | while read -r line; do log "bootstrap: $line"; done \
                || warn "Bootstrap failed (run manually: augur bootstrap)"
        else
            warn "LibreChat not ready — run bootstrap manually: augur bootstrap"
        fi
    fi

    # ── 12. Post-install checks ──
    echo ""
    echo -e "${CYAN}── Post-install checks ──${NC}"
    echo ""

    for svc in librechat trading charts; do
        if [[ -f "$HOME/.config/systemd/user/${svc}.service" ]]; then
            log "$svc service: registered"
        else
            warn "$svc service: NOT registered"
        fi
    done

    if crontab -l 2>/dev/null | grep -q "augur cron"; then
        log "Cron: augur cron already scheduled"
    else
        log "Adding augur cron job..."
        log "  → crontab: */15 * * * * ~/bin/augur cron 2>&1 | logger -t augur-cron"
        ( crontab -l 2>/dev/null || true; echo "*/15 * * * * ~/bin/augur cron 2>&1 | logger -t augur-cron" ) | crontab - \
            && log "Cron: augur cron scheduled" \
            || warn "Failed to add cron job — add manually: crontab -e"
    fi

    # ── Done ──
    local UBER="${UBER_HOST:-$(hostname -f 2>/dev/null || echo "$USER.uber.space")}"
    echo ""
    echo -e "${CYAN}══════════════════════════════════════════${NC}"
    echo -e "${GREEN}✓${NC} Installation complete!"
    echo -e "  Augur ${_INSTALL_SHA} (${_INSTALL_COMMIT_DATE})"
    echo -e "${CYAN}══════════════════════════════════════════${NC}"
    echo ""

    if [[ "$NEED_STACK_ENV" == true ]] || [[ "$NEED_APP_ENV" == true ]]; then
        echo -e "${YELLOW}New .env files were created and need your API keys.${NC}"
        echo ""
        if [[ -t 0 ]]; then
            if [[ "$NEED_STACK_ENV" == true ]]; then
                echo -e "${CYAN}[1/2]${NC} Signals stack config — set MONGO_URI_SIGNALS (optional API keys)"
                echo -e "      ${YELLOW}Note: MONGO_URI_SIGNALS is also set in LibreChat's .env (step 2)${NC}"
                echo -e "      ${YELLOW}$STACK/.env${NC}"
                read -rp "      Open in nano now? [Y/n] " ans
                if [[ "${ans:-Y}" =~ ^[Yy]?$ ]]; then nano "$STACK/.env"; fi
                echo ""
            fi
            if [[ "$NEED_APP_ENV" == true ]]; then
                echo -e "${CYAN}[2/2]${NC} LibreChat config — set MONGO_URI + LLM API key(s)"
                echo -e "      ${YELLOW}$APP/.env${NC}"
                read -rp "      Open in nano now? [Y/n] " ans
                if [[ "${ans:-Y}" =~ ^[Yy]?$ ]]; then nano "$APP/.env"; fi
                echo ""
            fi
        else
            echo -e "  ${CYAN}Step 1:${NC} Configure signals stack"
            echo "    nano $STACK/.env"
            echo "    # Set MONGO_URI_SIGNALS=mongodb+srv://...  (optional API keys)"
            echo ""
            echo -e "  ${CYAN}Step 2:${NC} Configure LibreChat"
            echo "    nano $APP/.env"
            echo "    # Set MONGO_URI=mongodb+srv://..."
            echo "    # Set at least one LLM key (many free tiers — see docs/llm-keys.md)"
            echo ""
        fi
    fi

    echo -e "  ${CYAN}Start:${NC}"
    echo "    systemctl --user start librechat"
    echo ""
    echo -e "  ${CYAN}Access:${NC}"
    echo "    https://${UBER}"
    echo "    (first user to register becomes admin)"
    echo ""
    echo -e "  ${CYAN}Seed agents:${NC} (after first login)"
    echo "    augur agents you@example.com yourpassword"
    echo "    augur agents --dry-run        # preview only"
    echo ""
    echo -e "  ${CYAN}Ops:${NC}"
    echo "    augur help                    # all commands"
    echo "    augur pull                    # quick git-pull update (dev)"
    echo "    augur u                       # release update (prod)"
    echo ""
}

_do_install "$@"
}
_main "$@"
