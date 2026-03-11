#!/bin/bash
# Augur ops — single entry point for install + daily ops
#
# Fresh install (one-liner, downloads prebuilt LibreChat from GitHub Release):
#   curl -sL https://raw.githubusercontent.com/ManuelKugelmann/Augur/main/librechat-uberspace/scripts/Augur.sh | bash
#
# After install:
#   augur help              # show all commands
#   augur install           # re-run full installer (idempotent)
#
# Installed as ~/bin/augur and ~/bin/Augur
set -euo pipefail

# ── Abort trap: Ctrl+C or SIGTERM → immediate full exit ──
_abort() {
    # Disable trap first to prevent recursive invocation
    # (kill 0 sends SIGTERM to our process group, which includes us)
    trap - INT TERM
    echo -e "\n\033[0;31m✗\033[0m Aborted." >&2
    # Kill child processes but not ourselves (avoid recursion + curl segfault)
    kill 0 2>/dev/null || true
    exit 130
}
trap '_abort' INT TERM

# ── Defaults (work before repo/config exist) ──
# These defaults are needed for the curl|bash one-liner where deploy.conf
# doesn't exist yet.  Once the repo is cloned, deploy.conf is sourced below
# and its values take effect for all subsequent variable expansions.
GH_USER="${GH_USER:-ManuelKugelmann}"
GH_REPO="${GH_REPO:-Augur}"
STACK_DIR="${STACK_DIR:-$HOME/augur}"
APP_DIR="${APP_DIR:-$HOME/LibreChat}"
LC_PORT="${LC_PORT:-3080}"
NODE_VERSION="${NODE_VERSION:-22}"
BRANCH="${BRANCH:-main}"

# ── Load central config if available ──
_script_conf=""
if [[ -n "${BASH_SOURCE[0]:-}" ]]; then
    _script_conf="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." 2>/dev/null && pwd)/deploy.conf"
fi
for _conf in "$STACK_DIR/deploy.conf" "$_script_conf"; do
    [[ -n "$_conf" ]] && [[ -f "$_conf" ]] && { source "$_conf"; break; }
done
unset _conf _script_conf

APP="${APP_DIR:-$HOME/LibreChat}"
STACK="${STACK_DIR:-$HOME/augur}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
die()  { echo -e "${RED}✗${NC} $1" >&2; exit 1; }

# ── Platform detection: U7 (supervisord) vs U8 (systemd) ──
_is_u8() { [[ -f /etc/arch-release ]]; }

# ── Service management (abstracts supervisord vs systemd) ──
_svc_start()   { if _is_u8; then systemctl --user start "$1" 2>/dev/null; else supervisorctl start "$1" 2>/dev/null; fi; }
_svc_stop()    { if _is_u8; then systemctl --user stop "$1" 2>/dev/null; else supervisorctl stop "$1" 2>/dev/null; fi; }
_svc_restart() { if _is_u8; then systemctl --user restart "$1" 2>/dev/null; else supervisorctl restart "$1" 2>/dev/null; fi; }
_svc_status()  { if _is_u8; then systemctl --user status "$1" --no-pager 2>/dev/null; else supervisorctl status "$1" 2>/dev/null; fi; }
_svc_logs()    { if _is_u8; then journalctl --user -u "$1" -f; else supervisorctl tail -f "$1"; fi; }
_svc_reload()  {
    if _is_u8; then
        systemctl --user daemon-reload 2>/dev/null || true
    else
        supervisorctl reread 2>/dev/null || true
        supervisorctl update 2>/dev/null || true
    fi
}

# ── Web backend (abstracts U7 set vs U8 add) ──
_web_backend() {
    local path="$1" port="$2"
    if _is_u8; then
        uberspace web backend add "$path" port "$port" --force 2>/dev/null
    else
        uberspace web backend set "$path" --http --port "$port" 2>/dev/null
    fi
}

# ── pip install helper (U7: pin pandas<3 to avoid slow source builds) ──
_pip_upgrade() {
    local pip="$1" min_ver=22
    local ver; ver=$("$pip" --version | awk '{print $2}' | cut -d. -f1)
    if (( ver >= min_ver )); then
        log "pip $ver is recent enough (>=$min_ver), skipping upgrade"
        return 0
    fi
    log "pip $ver < $min_ver, upgrading..."
    timeout 60 "$pip" install --upgrade pip
}

_pip_install() {
    local pip="$1" req="$2"
    local constraint
    constraint=$(mktemp)
    # U7 (CentOS 7, glibc 2.17): pandas 3.x has no pre-built wheel, cap to 2.x
    # U8: empty constraint file (no-op)
    if ! _is_u8; then echo 'pandas<3' > "$constraint"; fi
    timeout 180 "$pip" install --prefer-binary -c "$constraint" -r "$req" "${@:3}"
    rm -f "$constraint"
}

# ── HTTP helpers ──
gh_curl() {
    curl -sf "$@"
}

# Robust file download with progress and retries
# Usage: _download <url> <output-file> [description]
_download() {
    local url="$1" out="$2" desc="${3:-file}"
    local retries=4 attempt=0 delay=2 rc=0

    # Fetch file size for progress display (best-effort)
    local size_bytes=""
    size_bytes=$(curl -sfI -L "$url" 2>/dev/null | grep -i '^content-length:' | tail -1 | tr -d '[:space:]' | cut -d: -f2 || true)
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
        if command -v wget &>/dev/null && [[ "$url" == http://* || "$url" == https://* ]]; then
            # Use -q (quiet) — piping progress through grep caused pipe
            # backpressure stalls (same class of bug as the pv/tar fix)
            wget -q --timeout=30 --tries=1 \
                 -O "$out" "$url" \
                || rc=$?
        else
            curl -fL --progress-bar --connect-timeout 15 --max-time 600 \
                 -o "$out" "$url" \
                || rc=$?
        fi

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

# ── Resolve LibreChat bundle URL from GitHub Releases ──
# Sets global: _BUNDLE_URL, _BUNDLE_TAG
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

    # Fallback: rolling "librechat-build" prerelease tag
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

# ── Download, extract, and install/update LibreChat bundle ──
# Usage: _lc_download_and_setup [--skip-if-current]
#   --skip-if-current: skip if installed version matches bundle version
# Returns 0 on success/skip, dies on failure
_lc_download_and_setup() {
    local skip_current=false
    [[ "${1:-}" == "--skip-if-current" ]] && skip_current=true

    _resolve_bundle_url
    [[ -z "$_BUNDLE_URL" ]] && return 1

    # Check installed version against release tag before downloading
    if [[ "$skip_current" == true ]]; then
        local installed_ver=""
        [[ -f "$APP/.version" ]] && installed_ver=$(cat "$APP/.version")
        if [[ -n "$installed_ver" && -n "$_BUNDLE_TAG" ]]; then
            # Strip leading 'v' from tag for comparison
            local tag_ver="${_BUNDLE_TAG#v}"
            if [[ "$installed_ver" == "$tag_ver" || "$installed_ver" == "$_BUNDLE_TAG" ]]; then
                log "LibreChat already up-to-date (${installed_ver})"
                return 0
            fi
            log "Updating LibreChat ${installed_ver} → ${_BUNDLE_TAG}..."
        fi
    fi

    local lc_tmp
    # Use $HOME for temp dir — /tmp is tmpfs on U8 (Arch/systemd) with a size
    # cap; large bundles fill it and tar stalls. Home dir is on real disk.
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
    # Extract directly (no pv pipe — piping through pv throttles tar to KiB/s
    # on large archives with many small files due to 64KB pipe buffer backpressure)
    tar xzf "$lc_tmp/bundle.tar.gz" -C "$lc_tmp/app"
    log "Extraction complete"

    local bundle_ver=""
    [[ -f "$lc_tmp/app/.version" ]] && bundle_ver=$(cat "$lc_tmp/app/.version")
    [[ -z "$bundle_ver" ]] && bundle_ver="${_BUNDLE_TAG:-unknown}"

    log "LibreChat version: ${bundle_ver}"
    log "Running setup..."
    bash "$STACK/librechat-uberspace/scripts/setup.sh" "$lc_tmp/app" "$bundle_ver"
    return 0
}

# ── Auto-detect: piped with no args → install ──
CMD="${1:-help}"
if [[ "$CMD" == "help" ]] && ! [[ -d "$STACK/.git" ]]; then
    CMD="install"
fi

# ═══════════════════════════════════════════════
#  install — full install/update (idempotent)
#    augur install        → prebuilt release bundle from GitHub Releases
# ═══════════════════════════════════════════════
_do_install() {
    # Track whether .env files are new (need editing)
    local NEED_STACK_ENV=false
    local NEED_APP_ENV=false

    echo -e "${CYAN}══════════════════════════════════════════${NC}"
    echo -e "${CYAN} Augur + LibreChat → Uberspace ${NC}"
    echo -e "${CYAN}══════════════════════════════════════════${NC}"
    echo ""

    # ── 1. Node.js ──────────────────────────────
    if _is_u8; then
        # U8: Node.js is system-provided, no version management CLI
        command -v node &>/dev/null || die "Node.js not available"
        log "Node.js $(node -v) (U8 system-provided)"
    else
        local current_node
        current_node="$(node -v 2>/dev/null | sed 's/^v//' | cut -d. -f1)" || true
        if [[ "$current_node" != "$NODE_VERSION" ]]; then
            log "Setting Node.js ${NODE_VERSION} (current: ${current_node:-none})..."
            uberspace tools version use node "$NODE_VERSION" || warn "Failed to set Node.js version via uberspace CLI"
        fi
        command -v node &>/dev/null || die "Node.js not available"
        log "Node.js $(node -v)"
    fi

    # ── 2. Clone or update repo ─────────────────
    if [[ -d "$STACK/.git" ]]; then
        log "Repo exists at $STACK, pulling latest..."
        git -C "$STACK" pull --ff-only origin "$BRANCH" 2>/dev/null || \
            { git -C "$STACK" fetch origin "$BRANCH" && \
              git -C "$STACK" reset --hard "origin/$BRANCH"; }
        log "Repo updated"
    else
        log "Cloning repo..."
        git clone -b "$BRANCH" "https://github.com/${GH_USER}/${GH_REPO}.git" "$STACK"
        log "Cloned → $STACK"
    fi

    # ── Source central config now that it exists ─
    [[ -f "$STACK/deploy.conf" ]] && source "$STACK/deploy.conf"

    # ── 3. Python venv ──────────────────────────
    # Resolve Python binary: try explicit PYTHON_VERSION first, then scan
    # descending 3.13→3.10, then bare python3 (works on U7 + U8 + generic Linux)
    PYTHON_BIN=""
    for _py in "python${PYTHON_VERSION:-}" python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
        [[ -z "$_py" || "$_py" == "python" ]] && continue
        if command -v "$_py" &>/dev/null && \
           "$_py" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
            PYTHON_BIN="$_py"; break
        fi
    done
    [[ -z "$PYTHON_BIN" ]] && die "Python 3.10+ not found. On U7: check python3.12 --version. On U8: check python3 --version."
    _pyver=$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    log "Using $PYTHON_BIN (Python $_pyver)"

    if [[ -d "$STACK/venv" ]]; then
        log "Python venv exists, updating deps..."
    else
        log "Creating Python venv..."
        # Use --without-pip: plain venv creation is instant.
        # ensurepip (the default) can stall with no output on U8 / Ubuntu.
        "$PYTHON_BIN" -m venv --without-pip "$STACK/venv"
        log "Bootstrapping pip inside venv..."
        timeout 60 "$STACK/venv/bin/python" -m ensurepip --upgrade \
            || die "ensurepip failed or timed out"
    fi
    _pip_upgrade "$STACK/venv/bin/pip" \
        || die "pip upgrade failed or timed out"
    log "Installing requirements..."
    _pip_install "$STACK/venv/bin/pip" "$STACK/requirements.txt" \
        || die "pip install requirements failed or timed out"
    log "Python venv ready"

    # ── 4. Signals stack .env ───────────────────
    if [[ ! -f "$STACK/.env" ]]; then
        cp "$STACK/.env.example" "$STACK/.env"
        NEED_STACK_ENV=true
        log "Created $STACK/.env (needs configuration)"
    else
        log "Signals .env already exists"
    fi

    # ── 5. Register services (supervisord on U7, systemd on U8) ──
    log "Registering services..."

    if _is_u8; then
        mkdir -p ~/.config/systemd/user ~/logs

        # trading: combined MCP server (store + 12 domains) via streamable-http
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

        # charts: HTTP chart server
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
        systemctl --user enable trading 2>/dev/null || true
        systemctl --user enable charts 2>/dev/null || true
    else
        mkdir -p ~/etc/services.d ~/logs

        # trading: combined MCP server (store + 12 domains) via streamable-http
        # Uses bash -c to source .env (which may contain MongoDB URIs with special chars)
        # so we don't need to escape values for supervisord's environment= syntax.
        cat > ~/etc/services.d/trading.ini << SVCEOF
[program:trading]
directory=${STACK}
command=bash -c 'set -a; [ -f ${STACK}/.env ] && . ${STACK}/.env; set +a; export MCP_TRANSPORT=http MCP_PORT=8071; exec ${STACK}/venv/bin/python src/servers/combined_server.py'
autostart=true
autorestart=true
startsecs=10
SVCEOF

        # charts: HTTP chart server
        cat > ~/etc/services.d/charts.ini << SVCEOF
[program:charts]
directory=${STACK}
command=${STACK}/venv/bin/python src/store/charts.py
autostart=true
autorestart=true
startsecs=60
SVCEOF
    fi

    # Register /charts route to chart server port
    _web_backend /charts 8066 || warn "Failed to set /charts web backend"
    log "Services registered (trading, charts)"

    # ── 6. LibreChat — download prebuilt release bundle ──
    #       Bundle is a vanilla LibreChat build, versioned by LC's package.json + commit.
    local NEED_LC_SETUP=false
    local _pre_ver=""
    [[ -f "$APP/.version" ]] && _pre_ver=$(cat "$APP/.version")
    [[ ! -f "$APP/.env" ]] && NEED_APP_ENV=true

    if ! _lc_download_and_setup --skip-if-current; then
        die "No prebuilt LibreChat release found. Create one via: Actions → Release LibreChat Bundle → Run workflow (or: git tag v0.x.0 && git push --tags)"
    fi

    # Detect whether setup.sh actually ran (version changed or fresh install)
    local _post_ver=""
    [[ -f "$APP/.version" ]] && _post_ver=$(cat "$APP/.version")
    if [[ "$_pre_ver" != "$_post_ver" ]] || [[ -z "$_pre_ver" ]]; then
        NEED_LC_SETUP=true
    fi

    if [[ "$NEED_LC_SETUP" == false ]]; then
        # Even on re-run, ensure service + web backend are configured
        if _is_u8; then
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
                systemctl --user enable librechat 2>/dev/null || true
                log "Systemd service re-registered"
            fi
        else
            local SVC="$HOME/etc/services.d/librechat.ini"
            if [[ ! -f "$SVC" ]]; then
                mkdir -p "$(dirname "$SVC")"
                cat > "$SVC" <<SVCEOF
[program:librechat]
directory=${APP}
command=node --max-old-space-size=1024 api/server/index.js
environment=NODE_ENV=production
autostart=true
autorestart=true
startsecs=60
stopsignal=TERM
stopwaitsecs=10
SVCEOF
                supervisorctl reread 2>/dev/null
                supervisorctl add librechat 2>/dev/null || true
                log "Supervisord service re-registered"
            fi
        fi
        _web_backend / "${LC_PORT}" || warn "Failed to set web backend on port ${LC_PORT}"
    fi

    # ── 8. Install augur shortcut ─────────────────
    mkdir -p "$HOME/bin"
    cp "$STACK/librechat-uberspace/scripts/Augur.sh" "$HOME/bin/augur" 2>/dev/null || true
    chmod +x "$HOME/bin/augur" 2>/dev/null || true
    ln -sf "$HOME/bin/augur" "$HOME/bin/Augur" 2>/dev/null || true

    # ── 8b. Ensure ~/bin is in PATH via .bashrc (idempotent) ──
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

    # ── 9. Reload service manager ──────────────
    _svc_reload

    # ── 11. Auto-seed agents (if credentials available) ──
    if [[ -n "${AUGUR_SETUP_EMAIL:-}" ]] && [[ -n "${AUGUR_SETUP_PASSWORD:-}" ]]; then
        # Wait for LibreChat to become ready
        local LC_URL="http://localhost:${LC_PORT:-3080}"
        local LC_READY=false
        _svc_start librechat || true
        for i in $(seq 1 30); do
            if curl -sf "${LC_URL}/api/health" >/dev/null 2>&1; then
                LC_READY=true
                break
            fi
            sleep 2
        done
        if [[ "$LC_READY" == true ]]; then
            log "LibreChat is ready, seeding agents..."
            "$STACK/venv/bin/python" "$STACK/librechat-uberspace/scripts/seed-agents.py" \
                --email "$AUGUR_SETUP_EMAIL" --password "$AUGUR_SETUP_PASSWORD" \
                --base-url "$LC_URL" 2>&1 || warn "Agent seeding failed (seed manually: augur agents)"
        else
            warn "LibreChat not ready after 60s — seed agents manually: augur agents <email> <password>"
        fi
    fi

    # ── 12. Seed profile data into MongoDB (no overwrites) ──
    if [[ -x "$STACK/venv/bin/python" ]] && [[ -d "$STACK/profiles" ]]; then
        log "Seeding profiles from disk into MongoDB..."
        MONGO_URI_SIGNALS="${MONGO_URI_SIGNALS:-}" \
        "$STACK/venv/bin/python" -c "
import sys, os
sys.path.insert(0, os.path.join('$STACK', 'src', 'store'))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join('$STACK', '.env'))
except ImportError:
    pass
try:
    from server import seed_profiles
    result = seed_profiles('$STACK/profiles')
    if 'error' in result:
        print(f'Seed skipped: {result[\"error\"]}')
    else:
        total_seeded = sum(v.get('seeded', 0) for v in result.values())
        total_skipped = sum(v.get('skipped', 0) for v in result.values())
        print(f'Profiles seeded: {total_seeded} new, {total_skipped} existing (kept)')
except Exception as e:
    print(f'Seed skipped: {e}')
" 2>&1 | while read -r line; do log "$line"; done
    fi

    # ── 13. Bootstrap profile data via agent (if credentials available) ──
    if [[ -n "${AUGUR_AGENTS_API_KEY:-}" ]] && [[ -n "${AUGUR_BOOTSTRAP_AGENT_ID:-}" ]]; then
        local LC_URL="http://localhost:${LC_PORT:-3080}"
        local LC_READY=false
        for i in $(seq 1 15); do
            if curl -sf "${LC_URL}/api/health" >/dev/null 2>&1; then
                LC_READY=true
                break
            fi
            sleep 2
        done
        if [[ "$LC_READY" == true ]]; then
            log "Bootstrapping profile data via agent..."
            "$STACK/venv/bin/python" "$STACK/librechat-uberspace/scripts/bootstrap-data.py" \
                --api-key "$AUGUR_AGENTS_API_KEY" \
                --agent-id "$AUGUR_BOOTSTRAP_AGENT_ID" \
                --base-url "$LC_URL" \
                --timeseries 2>&1 | while read -r line; do log "bootstrap: $line"; done \
                || warn "Bootstrap failed (run manually: augur bootstrap)"
        else
            warn "LibreChat not ready — run bootstrap manually: augur bootstrap"
        fi
    fi

    # ── 14. Verify services and cron ──────────────
    echo ""
    echo -e "${CYAN}── Post-install checks ──${NC}"
    echo ""

    # Check service registrations
    for svc in librechat trading charts; do
        if _is_u8; then
            if [[ -f "$HOME/.config/systemd/user/${svc}.service" ]]; then
                log "$svc service: registered"
            else
                warn "$svc service: NOT registered"
            fi
        else
            if [[ -f "$HOME/etc/services.d/${svc}.ini" ]]; then
                log "$svc service: registered"
            else
                warn "$svc service: NOT registered"
            fi
        fi
    done

    # Check cron
    if crontab -l 2>/dev/null | grep -q "augur cron"; then
        log "Cron: augur cron scheduled"
    else
        warn "Cron: augur cron not scheduled"
        echo -e "      Add with: ${CYAN}crontab -e${NC}"
        echo -e "      Line:     ${CYAN}*/15 * * * * ~/bin/augur cron 2>&1 | logger -t augur-cron${NC}"
    fi

    # ── Done ────────────────────────────────────
    local UBER="${UBER_HOST:-$(hostname -f 2>/dev/null || echo "$USER.uber.space")}"
    echo ""
    echo -e "${CYAN}══════════════════════════════════════════${NC}"
    echo -e "${GREEN}✓${NC} Installation complete!"
    echo -e "${CYAN}══════════════════════════════════════════${NC}"
    echo ""

    # ── Interactive config if .env files are new ─
    if [[ "$NEED_STACK_ENV" == true ]] || [[ "$NEED_APP_ENV" == true ]]; then
        echo -e "${YELLOW}New .env files were created and need your API keys.${NC}"
        echo ""

        if [[ -t 0 ]]; then
            # Interactive terminal — offer to open nano
            if [[ "$NEED_STACK_ENV" == true ]]; then
                echo -e "${CYAN}[1/2]${NC} Signals stack config — set MONGO_URI_SIGNALS (optional API keys)"
                echo -e "      ${YELLOW}Note: MONGO_URI_SIGNALS is also set in LibreChat's .env (step 2)${NC}"
                echo -e "      ${YELLOW}$STACK/.env${NC}"
                read -rp "      Open in nano now? [Y/n] " ans
                if [[ "${ans:-Y}" =~ ^[Yy]?$ ]]; then
                    nano "$STACK/.env"
                fi
                echo ""
            fi

            if [[ "$NEED_APP_ENV" == true ]]; then
                echo -e "${CYAN}[2/2]${NC} LibreChat config — set MONGO_URI + LLM API key(s)"
                echo -e "      ${YELLOW}$APP/.env${NC}"
                read -rp "      Open in nano now? [Y/n] " ans
                if [[ "${ans:-Y}" =~ ^[Yy]?$ ]]; then
                    nano "$APP/.env"
                fi
                echo ""
            fi
        else
            # Piped (curl|bash) — can't do interactive nano, print instructions
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
    if _is_u8; then
        echo "    systemctl --user start librechat"
    else
        echo "    supervisorctl start librechat"
    fi
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
    echo "    augur u                    # release update (prod)"
    echo ""
}

# ═══════════════════════════════════════════════
#  Command dispatch
# ═══════════════════════════════════════════════
case "$CMD" in
    s|status)
        _svc_status librechat || echo "librechat: not registered"
        _svc_status trading || true
        _svc_status charts || true
        echo -e "${CYAN}Version:${NC} $(cat "$APP/.version" 2>/dev/null || echo 'unknown')"
        echo -e "${CYAN}Host:${NC} ${UBER_HOST:-$(hostname -f 2>/dev/null || echo 'unknown')}"
        echo -e "${CYAN}Platform:${NC} $(_is_u8 && echo 'U8 (Arch/systemd)' || echo 'U7 (CentOS/supervisord)')"
        ;;
    r|restart)
        _svc_restart librechat
        _svc_restart trading || true
        echo -e "${GREEN}✓${NC} Restarted (librechat + trading)"
        ;;
    l|logs)
        _svc_logs librechat
        ;;
    testrun)
        # Run LibreChat (or trading server) in the foreground to see errors directly.
        # Usage: augur testrun [trading]
        _TARGET="${2:-librechat}"
        case "$_TARGET" in
            librechat)
                echo -e "${CYAN}Stopping librechat service...${NC}"
                _svc_stop librechat 2>/dev/null || true
                echo -e "${CYAN}Starting LibreChat in foreground (Ctrl+C to stop)...${NC}"
                cd "$APP"
                NODE_ENV=production exec node --max-old-space-size=1024 api/server/index.js
                ;;
            trading)
                echo -e "${CYAN}Stopping trading service...${NC}"
                _svc_stop trading 2>/dev/null || true
                echo -e "${CYAN}Starting trading server in foreground (Ctrl+C to stop)...${NC}"
                cd "$STACK"
                set -a; [[ -f "$STACK/.env" ]] && . "$STACK/.env"; set +a
                export MCP_TRANSPORT=http MCP_PORT=8071
                exec "$STACK/venv/bin/python" src/servers/combined_server.py
                ;;
            *)
                echo "Usage: augur testrun [librechat|trading]"
                echo "  augur testrun             Run LibreChat in foreground"
                echo "  augur testrun trading     Run trading server in foreground"
                ;;
        esac
        ;;
    v|version)
        cat "$APP/.version" 2>/dev/null || echo "unknown"
        ;;
    u|update)
        echo -e "${CYAN}Pulling latest release...${NC}"
        _lc_download_and_setup || die "No prebuilt LibreChat release found."
        ;;
    pull)
        # Quick dev update — git pull the stack repo, re-copy configs, restart
        echo -e "${CYAN}Dev update via git pull...${NC}"
        git -C "$STACK" pull --ff-only
        VER="dev-$(git -C "$STACK" rev-parse --short HEAD)"

        # Re-copy scripts and config
        mkdir -p "$APP/scripts" "$APP/config"
        cp "$STACK/librechat-uberspace/scripts/"*.sh "$APP/scripts/" 2>/dev/null || true
        if [[ -f "$STACK/librechat-uberspace/config/librechat.yaml" ]] && [[ ! -f "$APP/librechat.yaml" ]]; then
            cp "$STACK/librechat-uberspace/config/librechat.yaml" "$APP/librechat.yaml"
            sed -i "s|__HOME__|$HOME|g" "$APP/librechat.yaml"
        fi

        # Update augur/Augur shortcuts
        cp "$STACK/librechat-uberspace/scripts/Augur.sh" "$HOME/bin/augur" 2>/dev/null || true
        chmod +x "$HOME/bin/augur" 2>/dev/null || true
        ln -sf "$HOME/bin/augur" "$HOME/bin/Augur" 2>/dev/null || true

        # Update Python deps if changed
        if [[ -d "$STACK/venv" ]]; then
            _pip_upgrade "$STACK/venv/bin/pip" \
                || die "pip upgrade failed or timed out"
            log "Installing requirements..."
            _pip_install "$STACK/venv/bin/pip" "$STACK/requirements.txt" \
                || die "pip install requirements failed or timed out"
        else
            warn "Python venv not found at $STACK/venv — run 'augur install' first"
        fi

        echo "$VER" > "$APP/.version"
        _svc_restart librechat || true
        _svc_restart trading || true
        echo -e "${GREEN}✓${NC} Updated to ${VER} via git pull"
        ;;
    install)
        _do_install "$@"
        ;;
    rb|rollback)
        if [[ ! -d "${APP}.prev" ]]; then
            echo -e "${RED}✗${NC} No previous version to rollback to"
            exit 1
        fi
        _svc_stop librechat
        rm -rf "$APP"
        mv "${APP}.prev" "$APP"
        _svc_start librechat
        echo -e "${GREEN}✓${NC} Rolled back to $(cat "$APP/.version" 2>/dev/null || echo 'unknown')"
        ;;
    backup)
        if [[ -f "$STACK/venv/bin/python" ]]; then
            STACK="$STACK" "$STACK/venv/bin/python" "$STACK/scripts/mongo-backup.py" backup
        else
            echo -e "${RED}✗${NC} Python venv not found. Run: augur install"
            exit 1
        fi
        ;;
    restore)
        if [[ -f "$STACK/venv/bin/python" ]]; then
            STACK="$STACK" "$STACK/venv/bin/python" "$STACK/scripts/mongo-backup.py" restore "${2:-}"
        else
            echo -e "${RED}✗${NC} Python venv not found. Run: augur install"
            exit 1
        fi
        ;;
    backups)
        if [[ -f "$STACK/venv/bin/python" ]]; then
            STACK="$STACK" "$STACK/venv/bin/python" "$STACK/scripts/mongo-backup.py" list
        else
            echo -e "${RED}✗${NC} Python venv not found. Run: augur install"
            exit 1
        fi
        ;;
    cron)
        # ── Unified cron hook (every 15 min) ─────────────────────
        # Install: crontab -e → */15 * * * * ~/bin/augur cron 2>&1 | logger -t augur-cron
        # Internally gates tasks by interval so only one cron entry is needed.
        HOUR=$(date +%H)
        MIN=$(date +%M)
        DOW=$(date +%u)   # 1=Mon .. 7=Sun

        _cron_log() { echo "[augur-cron] $1"; }

        # ── Daily at 02:00 UTC: compact old snapshots to archive ──
        if [[ "$HOUR" == "02" ]]; then
            sleep "$((RANDOM % 300))"   # 0–5 min extra jitter for daily tasks
            _cron_log "running daily compact"
            if [[ -f "$STACK/venv/bin/python" ]]; then
                STACK="$STACK" "$STACK/venv/bin/python" - <<'PYEOF'
import os, sys
stack = os.environ.get("STACK", os.path.expanduser("~/augur"))
sys.path.insert(0, os.path.join(stack, "src", "store"))
sys.path.insert(0, os.path.join(stack, "src", "servers"))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(stack, ".env"))
except ImportError:
    pass
from server import compact, _snap_col, VALID_KINDS

for kind in VALID_KINDS:
    try:
        col = _snap_col(kind)
    except Exception as e:
        print(f"[augur-cron] compact skip {kind}: {e}")
        continue
    pipeline = [
        {"$group": {"_id": {"entity": "$meta.entity", "type": "$meta.type"}}},
    ]
    try:
        combos = list(col.aggregate(pipeline))
    except Exception as e:
        print(f"[augur-cron] compact skip {kind}: {e}")
        continue
    for c in combos:
        eid = c["_id"]["entity"]
        etype = c["_id"]["type"]
        result = compact(kind, eid, etype, older_than_days=90, bucket="month")
        status = result.get("status", "error")
        if status == "ok":
            print(f"[augur-cron] compacted {kind}/{eid}/{etype}: {result['buckets_created']} buckets, {result['snapshots_deleted']} removed")
        elif status != "nothing_to_compact":
            print(f"[augur-cron] compact {kind}/{eid}/{etype}: {status}")
PYEOF
            else
                _cron_log "python venv not found, skipping compact"
            fi

            # ── Daily at 02:00 UTC: MongoDB backup (rolling) ──
            _cron_log "running daily backup"
            if [[ -f "$STACK/venv/bin/python" ]] && [[ -f "$STACK/scripts/mongo-backup.py" ]]; then
                STACK="$STACK" "$STACK/venv/bin/python" "$STACK/scripts/mongo-backup.py" backup 2>&1 \
                    | while read -r line; do _cron_log "backup: $line"; done
            fi
        fi

        # ── Every 30 min: Claude token health check ──
        if [[ -f "$HOME/.claude-auth.env" ]] && [[ "$((10#$MIN % 30))" -eq 0 ]]; then
            if [[ -x "$HOME/bin/claude-auth-daemon.sh" ]]; then
                "$HOME/bin/claude-auth-daemon.sh" --once 2>&1 | while read -r line; do _cron_log "$line"; done
            fi
        fi

        # ── Every 6 hours (00, 06, 12, 18): invoke cron-planner agent ──
        if [[ "$((10#$HOUR % 6))" -eq 0 ]] && [[ "$((10#$MIN))" -lt 15 ]]; then
            sleep "$((RANDOM % 180))"   # 0–3 min jitter for agent calls
            if [[ -n "${AUGUR_AGENTS_API_KEY:-}" ]]; then
                LC_URL="http://localhost:${LC_PORT:-3080}"
                # Find cron-planner agent ID from agents list
                CRON_AGENT_ID=$("$STACK/venv/bin/python" -c "
import httpx, sys
try:
    r = httpx.get('${LC_URL}/api/agents/v1/models',
                   headers={'Authorization': 'Bearer ${AUGUR_AGENTS_API_KEY}'},
                   timeout=10)
    if r.status_code == 200:
        for m in r.json().get('data', []):
            if 'cron' in m.get('id', '').lower() or 'Cron' in m.get('name', ''):
                print(m['id']); sys.exit(0)
    sys.exit(1)
except Exception:
    sys.exit(1)
" 2>/dev/null) || CRON_AGENT_ID=""

                if [[ -n "$CRON_AGENT_ID" ]]; then
                    _cron_log "invoking cron-planner agent ($CRON_AGENT_ID)"
                    "$STACK/venv/bin/python" -c "
import httpx, json, sys
try:
    r = httpx.post('${LC_URL}/api/agents/v1/chat/completions',
                    headers={'Authorization': 'Bearer ${AUGUR_AGENTS_API_KEY}',
                             'Content-Type': 'application/json'},
                    json={'model': '${CRON_AGENT_ID}',
                          'messages': [{'role': 'user',
                                        'content': 'Execute your periodic routine: '
                                                   '1) Read plans (store_get_notes kind=plan). '
                                                   '2) Check risk status. '
                                                   '3) For watched entities, refresh data via daaugur agents. '
                                                   '4) Run analysis if data is stale. '
                                                   '5) Update plans with results. '
                                                   '6) Log summary as event.'}],
                          'stream': False},
                    timeout=300)
    if r.status_code == 200:
        data = r.json()
        content = data.get('choices', [{}])[0].get('message', {}).get('content', '')
        print(f'OK: {content[:200]}')
    else:
        print(f'ERROR: {r.status_code} {r.text[:200]}', file=sys.stderr)
except Exception as e:
    print(f'ERROR: {e}', file=sys.stderr)
" 2>&1 | while read -r line; do _cron_log "cron-planner: $line"; done
                else
                    _cron_log "cron-planner agent not found (seed agents: augur agents)"
                fi
            fi
        fi

        _cron_log "done (hour=$HOUR dow=$DOW)"
        ;;
    proxy)
        PROXY_PORT="${CLIPROXY_PORT:-8317}"
        PROXY_CONFIG="$HOME/.cli-proxy-api/config.yaml"
        PROXY_AUTH="$HOME/.claude-auth.env"
        if _is_u8; then
            PROXY_SVC="$HOME/.config/systemd/user/cliproxyapi.service"
        else
            PROXY_SVC="$HOME/etc/services.d/cliproxyapi.ini"
        fi
        SUB="${2:-help}"
        case "$SUB" in
            setup)
                # Install CLIProxyAPI
                if ! command -v cliproxyapi &>/dev/null; then
                    log "Installing CLIProxyAPI..."
                    npm install -g cliproxyapi
                fi
                log "CLIProxyAPI $(cliproxyapi --version 2>/dev/null || echo 'installed')"

                # Create config
                mkdir -p "$HOME/.cli-proxy-api"
                if [[ ! -f "$PROXY_CONFIG" ]]; then
                    cat > "$PROXY_CONFIG" << 'CFGEOF'
port: 8317
remote-management:
  allow-remote: false
  secret-key: ""
auth-dir: "~/.cli-proxy-api"
auth:
  providers: []
debug: false
CFGEOF
                    log "Created $PROXY_CONFIG"
                else
                    log "Config already exists at $PROXY_CONFIG"
                fi

                # Check token
                if [[ ! -f "$PROXY_AUTH" ]]; then
                    warn "No token found at $PROXY_AUTH"
                    echo "  Run on a machine with a browser:"
                    echo "    claude setup-token"
                    echo "  Then save the token:"
                    echo "    echo 'CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-...' > $PROXY_AUTH"
                    echo "    chmod 600 $PROXY_AUTH"
                fi

                # Register service
                mkdir -p "$(dirname "$PROXY_SVC")"
                if _is_u8; then
                    cat > "$PROXY_SVC" << SVCEOF
[Install]
WantedBy=default.target

[Service]
WorkingDirectory=${HOME}
EnvironmentFile=${PROXY_AUTH}
ExecStart=cliproxyapi --config ${PROXY_CONFIG}
Restart=always
RestartSec=10
SVCEOF
                else
                    if [[ -f "$PROXY_AUTH" ]]; then
                        # supervisord doesn't support EnvironmentFile, so we wrap the command
                        cat > "$PROXY_SVC" << SVCEOF
[program:cliproxyapi]
directory=${HOME}
command=bash -c 'source ${PROXY_AUTH} && exec cliproxyapi --config ${PROXY_CONFIG}'
autostart=true
autorestart=true
startsecs=10
SVCEOF
                    else
                        cat > "$PROXY_SVC" << SVCEOF
[program:cliproxyapi]
directory=${HOME}
command=cliproxyapi --config ${PROXY_CONFIG}
environment=HOME="${HOME}"
autostart=true
autorestart=true
startsecs=10
SVCEOF
                    fi
                fi
                _svc_reload
                log "Service registered (cliproxyapi)"

                # Install auth daemon
                cp "$STACK/librechat-uberspace/scripts/claude-auth-daemon.sh" "$HOME/bin/claude-auth-daemon.sh" 2>/dev/null || true
                chmod +x "$HOME/bin/claude-auth-daemon.sh" 2>/dev/null || true

                log "CLIProxyAPI setup complete"
                echo ""
                echo "  Next steps:"
                echo "    1. Add your token to $PROXY_AUTH (if not done)"
                echo "    2. augur proxy start"
                echo "    3. augur proxy test"
                echo "    4. Uncomment 'Claude Max' endpoint in librechat.yaml: augur yaml"
                echo "    5. augur restart"
                ;;
            start)
                _svc_start cliproxyapi
                log "CLIProxyAPI started"
                ;;
            stop)
                _svc_stop cliproxyapi
                log "CLIProxyAPI stopped"
                ;;
            status)
                _svc_status cliproxyapi || echo "cliproxyapi: not registered"
                ;;
            test)
                echo -e "${CYAN}Testing proxy at localhost:${PROXY_PORT}...${NC}"
                HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:${PROXY_PORT}/v1/models" 2>/dev/null || echo "000")
                if [[ "$HTTP_CODE" == "200" ]]; then
                    log "Proxy OK (HTTP 200)"
                    curl -s "http://localhost:${PROXY_PORT}/v1/models" | head -20
                elif [[ "$HTTP_CODE" == "000" ]]; then
                    die "Proxy not reachable. Run: augur proxy start"
                else
                    die "Proxy returned HTTP ${HTTP_CODE}"
                fi
                ;;
            token)
                if [[ -f "$PROXY_AUTH" ]]; then
                    # Show token prefix (safe) and file info
                    TOKEN_PREFIX=$(grep -o 'sk-ant-oat01-[a-zA-Z0-9_-]\{8\}' "$PROXY_AUTH" 2>/dev/null || echo "not found")
                    echo -e "${CYAN}Token:${NC} ${TOKEN_PREFIX}..."
                    echo -e "${CYAN}File:${NC} $PROXY_AUTH"
                    echo -e "${CYAN}Modified:${NC} $(stat -c '%y' "$PROXY_AUTH" 2>/dev/null || stat -f '%Sm' "$PROXY_AUTH" 2>/dev/null || echo 'unknown')"
                    echo -e "${YELLOW}Tokens expire after ~1 year. Renew with: claude setup-token${NC}"
                else
                    warn "No token file at $PROXY_AUTH"
                    echo "  Run: claude setup-token"
                fi
                ;;
            *)
                echo "  augur proxy setup    Install CLIProxyAPI + register service"
                echo "  augur proxy start    Start CLIProxyAPI"
                echo "  augur proxy stop     Stop CLIProxyAPI"
                echo "  augur proxy status   Show CLIProxyAPI status"
                echo "  augur proxy test     Test proxy endpoint"
                echo "  augur proxy token    Show token info"
                ;;
        esac
        ;;
    check|health)
        # ── Health check — verifiable on the deployed host ──
        PASS=0; FAIL=0; WARN=0; TOTAL=0
        _ok()   { PASS=$((PASS+1)); TOTAL=$((TOTAL+1)); echo -e "  ${GREEN}PASS${NC}  $1"; }
        _fail() { FAIL=$((FAIL+1)); TOTAL=$((TOTAL+1)); echo -e "  ${RED}FAIL${NC}  $1"; }
        _warn() { WARN=$((WARN+1)); TOTAL=$((TOTAL+1)); echo -e "  ${YELLOW}WARN${NC}  $1"; }
        _skip() { TOTAL=$((TOTAL+1)); echo -e "  ${CYAN}SKIP${NC}  $1"; }

        echo -e "${CYAN}── Health Check ──${NC}"
        echo ""

        # 1. Stack repo
        if [[ -d "$STACK/.git" ]]; then
            _ok "Stack repo exists at $STACK"
        else
            _fail "Stack repo missing at $STACK"
        fi

        # 2. deploy.conf
        if [[ -f "$STACK/deploy.conf" ]]; then
            _ok "deploy.conf present"
        else
            _fail "deploy.conf missing"
        fi

        # 3. Python venv
        if [[ -x "$STACK/venv/bin/python" ]]; then
            _ok "Python venv: $("$STACK/venv/bin/python" --version 2>&1)"
        else
            _fail "Python venv missing at $STACK/venv"
        fi

        # 4. Python deps
        if [[ -x "$STACK/venv/bin/python" ]]; then
            if "$STACK/venv/bin/python" -c "import fastmcp, httpx, pymongo, dotenv" 2>/dev/null; then
                _ok "Python deps: fastmcp, httpx, pymongo, dotenv"
            else
                _fail "Python deps: missing (run: $STACK/venv/bin/pip install -r $STACK/requirements.txt)"
            fi
        fi

        # 5. Node.js
        if command -v node &>/dev/null; then
            NODE_VER="$(node -v 2>/dev/null)"
            NODE_MAJOR="${NODE_VER#v}"
            NODE_MAJOR="${NODE_MAJOR%%.*}"
            if [[ "$NODE_MAJOR" -ge 20 ]]; then
                _ok "Node.js ${NODE_VER}"
            else
                _warn "Node.js ${NODE_VER} (recommend >= 20)"
            fi
        else
            _fail "Node.js not found"
        fi

        # 6. LibreChat installation
        if [[ -f "$APP/.version" ]]; then
            _ok "LibreChat installed: $(cat "$APP/.version")"
        else
            _fail "LibreChat not installed at $APP"
        fi

        # 7. LibreChat .env
        if [[ -f "$APP/.env" ]]; then
            if grep -q "MONGO_URI=" "$APP/.env" 2>/dev/null; then
                _ok "LibreChat .env with MONGO_URI"
            else
                _warn "LibreChat .env exists but MONGO_URI not set"
            fi
        else
            _fail "LibreChat .env missing"
        fi

        # 8. librechat.yaml
        if [[ -f "$APP/librechat.yaml" ]]; then
            if grep -q "mcpServers:" "$APP/librechat.yaml" 2>/dev/null; then
                _ok "librechat.yaml with MCP servers"
            else
                _warn "librechat.yaml exists but no mcpServers section"
            fi
        else
            _fail "librechat.yaml missing"
        fi

        # 9. Signals stack .env
        if [[ -f "$STACK/.env" ]]; then
            _ok "Signals .env present"
        else
            _warn "Signals .env missing (optional if run via LibreChat)"
        fi

        # 10. Services
        echo ""
        echo -e "${CYAN}── Services ($(_is_u8 && echo 'systemd' || echo 'supervisord')) ──${NC}"
        echo ""
        for svc in librechat trading charts cliproxyapi; do
            if _is_u8; then
                if systemctl --user is-active "$svc" &>/dev/null; then
                    _ok "$svc: RUNNING"
                elif systemctl --user is-enabled "$svc" &>/dev/null; then
                    _warn "$svc: STOPPED (enabled)"
                elif [[ -f "$HOME/.config/systemd/user/${svc}.service" ]]; then
                    _warn "$svc: STOPPED"
                else
                    _skip "$svc: not registered"
                fi
            else
                SVC_STATUS="$(supervisorctl status "$svc" 2>/dev/null || true)"
                if [[ -z "$SVC_STATUS" ]]; then
                    _skip "$svc: not registered"
                elif echo "$SVC_STATUS" | grep -q "RUNNING"; then
                    _ok "$svc: RUNNING"
                elif echo "$SVC_STATUS" | grep -q "STOPPED"; then
                    _warn "$svc: STOPPED"
                else
                    _fail "$svc: $(echo "$SVC_STATUS" | head -1)"
                fi
            fi
        done

        # 11. Web backends (uberspace routing)
        echo ""
        echo -e "${CYAN}── Web Backends ──${NC}"
        echo ""
        if command -v uberspace &>/dev/null; then
            WB_LIST="$(uberspace web backend list 2>/dev/null || true)"
            if [[ -n "$WB_LIST" ]]; then
                echo "$WB_LIST" | while read -r line; do
                    echo -e "  ${CYAN}│${NC} $line"
                done
                # Check for expected routes
                if echo "$WB_LIST" | grep -q "${LC_PORT:-3080}"; then
                    _ok "Web backend: / → port ${LC_PORT:-3080}"
                else
                    _warn "Web backend: / not routed to port ${LC_PORT:-3080}"
                fi
                if echo "$WB_LIST" | grep -q "8066"; then
                    _ok "Web backend: /charts → port 8066"
                else
                    _warn "Web backend: /charts not routed to port 8066"
                fi
            else
                _warn "Web backends: could not list (uberspace web backend list)"
            fi
        else
            _skip "Web backends: uberspace CLI not available"
        fi

        # 12. HTTP connectivity
        echo ""
        echo -e "${CYAN}── Connectivity ──${NC}"
        echo ""
        LC_CODE="$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:${LC_PORT:-3080}/" 2>/dev/null || echo "000")"
        if [[ "$LC_CODE" == "200" ]] || [[ "$LC_CODE" == "301" ]] || [[ "$LC_CODE" == "302" ]]; then
            _ok "LibreChat HTTP: ${LC_CODE} on port ${LC_PORT:-3080}"
        elif [[ "$LC_CODE" == "000" ]]; then
            _fail "LibreChat HTTP: not reachable on port ${LC_PORT:-3080}"
        else
            _warn "LibreChat HTTP: ${LC_CODE} on port ${LC_PORT:-3080}"
        fi

        # 13. Charts endpoint
        CHARTS_CODE="$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:8066/charts/" 2>/dev/null || echo "000")"
        if [[ "$CHARTS_CODE" != "000" ]]; then
            _ok "Charts HTTP: ${CHARTS_CODE} on port 8066"
        else
            _warn "Charts HTTP: not reachable on port 8066"
        fi

        # 14. CLIProxyAPI (only if configured)
        PROXY_PORT="${CLIPROXY_PORT:-8317}"
        if [[ -f "$HOME/.claude-auth.env" ]] || [[ -f "$HOME/etc/services.d/cliproxyapi.ini" ]] || [[ -f "$HOME/.config/systemd/user/cliproxyapi.service" ]]; then
            PROXY_CODE="$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:${PROXY_PORT}/v1/models" 2>/dev/null || echo "000")"
            if [[ "$PROXY_CODE" == "200" ]]; then
                _ok "CLIProxyAPI: OK on port ${PROXY_PORT}"
            elif [[ "$PROXY_CODE" == "401" ]]; then
                _fail "CLIProxyAPI: 401 — token expired (run: claude setup-token)"
            elif [[ "$PROXY_CODE" == "000" ]]; then
                _fail "CLIProxyAPI: not reachable on port ${PROXY_PORT}"
            else
                _warn "CLIProxyAPI: HTTP ${PROXY_CODE} on port ${PROXY_PORT}"
            fi
        else
            _skip "CLIProxyAPI: not configured"
        fi

        # 15. Profiles
        echo ""
        echo -e "${CYAN}── Data ──${NC}"
        echo ""
        if [[ -d "$STACK/profiles" ]]; then
            PROFILE_COUNT="$(find "$STACK/profiles" -name '*.json' -not -name 'INDEX_*' -not -path '*/SCHEMAS/*' 2>/dev/null | wc -l)"
            if [[ "$PROFILE_COUNT" -gt 0 ]]; then
                _ok "Profiles: ${PROFILE_COUNT} JSON files"
            else
                _warn "Profiles: directory exists but no profiles found"
            fi
        else
            _fail "Profiles directory missing"
        fi

        # 16. Cron
        if crontab -l 2>/dev/null | grep -q "augur cron"; then
            _ok "Cron: augur cron scheduled"
        else
            _warn "Cron: augur cron not scheduled (run: crontab -e)"
        fi

        # 17. Shell script syntax (quick)
        SYNTAX_OK=true
        for script in "$STACK/librechat-uberspace/scripts/"*.sh; do
            if ! bash -n "$script" 2>/dev/null; then
                _fail "Syntax error: $(basename "$script")"
                SYNTAX_OK=false
            fi
        done
        if [[ "$SYNTAX_OK" == true ]]; then
            _ok "Shell scripts: all pass syntax check"
        fi

        # 18. Run test suite if available and requested (augur check --test)
        if [[ "${2:-}" == "--test" ]] || [[ "${2:-}" == "-t" ]]; then
            echo ""
            echo -e "${CYAN}── Test Suite ──${NC}"
            echo ""

            # bats tests (exclude uberspace-only tests which need live services)
            if command -v bats &>/dev/null && [[ -d "$STACK/tests" ]]; then
                BATS_FILES=()
                for f in "$STACK/tests/"*.bats; do
                    # Skip uberspace-only tests unless we're actually on Uberspace
                    if [[ "$(basename "$f")" == "test_uberspace.bats" ]]; then
                        if [[ "$(hostname -f 2>/dev/null)" != *".uber.space" ]]; then
                            continue
                        fi
                    fi
                    BATS_FILES+=("$f")
                done
                if [[ ${#BATS_FILES[@]} -gt 0 ]]; then
                    if bats "${BATS_FILES[@]}" 2>&1; then
                        _ok "Bats tests: all passed"
                    else
                        _fail "Bats tests: some failures"
                    fi
                fi
            else
                if ! command -v bats &>/dev/null; then
                    _skip "Bats tests: bats not installed (npm i -g bats)"
                else
                    _skip "Bats tests: no tests found"
                fi
            fi

            # pytest tests
            if [[ -x "$STACK/venv/bin/python" ]] && "$STACK/venv/bin/python" -c "import pytest" 2>/dev/null; then
                if "$STACK/venv/bin/python" -m pytest "$STACK/tests/test_store.py" -q 2>&1; then
                    _ok "Pytest tests: all passed"
                else
                    _fail "Pytest tests: some failures"
                fi
            else
                _skip "Pytest tests: pytest not installed ($STACK/venv/bin/pip install pytest)"
            fi

            # Uberspace-only tests
            if [[ -f "$STACK/tests/test_uberspace.bats" ]]; then
                if [[ "$(hostname -f 2>/dev/null)" == *".uber.space" ]]; then
                    echo ""
                    echo -e "${CYAN}── Uberspace Live Tests ──${NC}"
                    echo ""
                    if bats "$STACK/tests/test_uberspace.bats" 2>&1; then
                        _ok "Uberspace tests: all passed"
                    else
                        _fail "Uberspace tests: some failures"
                    fi
                else
                    _skip "Uberspace tests: not on *.uber.space host"
                fi
            fi
        fi

        # ── Summary ──
        echo ""
        echo -e "${CYAN}── Summary ──${NC}"
        echo ""
        echo -e "  Total: ${TOTAL}   ${GREEN}Pass: ${PASS}${NC}   ${RED}Fail: ${FAIL}${NC}   ${YELLOW}Warn: ${WARN}${NC}"
        echo ""
        if [[ "${2:-}" != "--test" ]] && [[ "${2:-}" != "-t" ]]; then
            echo -e "  ${CYAN}Tip:${NC} Run with --test to also execute the test suite:"
            echo "    augur check --test"
            echo ""
        fi
        if [[ "$FAIL" -gt 0 ]]; then
            echo -e "  ${RED}Some checks failed. Review above for details.${NC}"
            exit 1
        elif [[ "$WARN" -gt 0 ]]; then
            echo -e "  ${YELLOW}All critical checks passed, some warnings.${NC}"
        else
            echo -e "  ${GREEN}All checks passed!${NC}"
        fi
        ;;
    env)
        ${EDITOR:-nano} "$APP/.env"
        ;;
    yaml)
        ${EDITOR:-nano} "$APP/librechat.yaml"
        ;;
    conf)
        ${EDITOR:-nano} "$STACK/deploy.conf"
        ;;
    bootstrap)
        # ── Bootstrap profile data via LibreChat Agents API ──
        # Instructs an agent (default: L4 cron-planner) to populate and enrich
        # profiles using MCP tools and web search. Additive: extends existing data.
        #
        # Usage:
        #   augur bootstrap                              # bootstrap all kinds
        #   augur bootstrap --kind countries             # bootstrap one kind
        #   augur bootstrap --batch-size 5               # smaller batches
        #   augur bootstrap --dry-run                    # preview prompts only
        #
        # Env vars: AUGUR_AGENTS_API_KEY, AUGUR_BOOTSTRAP_AGENT_ID
        BOOTSTRAP_API_KEY="${AUGUR_AGENTS_API_KEY:-}"
        BOOTSTRAP_AGENT_ID="${AUGUR_BOOTSTRAP_AGENT_ID:-}"

        if [[ "${2:-}" == "--dry-run" ]]; then
            "$STACK/venv/bin/python" "$STACK/librechat-uberspace/scripts/bootstrap-data.py" \
                --dry-run "${@:3}"
        elif [[ -z "$BOOTSTRAP_API_KEY" ]]; then
            echo -e "${YELLOW}Usage: augur bootstrap [--kind KIND] [--batch-size N] [--dry-run]${NC}"
            echo ""
            echo "  Bootstraps profile data via LibreChat Agents API."
            echo "  Enriches existing profiles and creates new ones using MCP tools."
            echo ""
            echo "  Required env vars:"
            echo "    AUGUR_AGENTS_API_KEY        LibreChat Agents API key"
            echo "    AUGUR_BOOTSTRAP_AGENT_ID    Agent ID (e.g. from 'augur agents' output)"
            echo ""
            echo "  augur bootstrap                        # all kinds"
            echo "  augur bootstrap --kind countries        # one kind"
            echo "  augur bootstrap --dry-run               # preview only"
        else
            LC_URL="http://localhost:${LC_PORT:-3080}"
            echo -e "${CYAN}Bootstrapping profiles via ${LC_URL}...${NC}"
            "$STACK/venv/bin/python" "$STACK/librechat-uberspace/scripts/bootstrap-data.py" \
                --api-key "$BOOTSTRAP_API_KEY" \
                --agent-id "$BOOTSTRAP_AGENT_ID" \
                --base-url "$LC_URL" \
                "${@:2}"
            echo -e "${GREEN}✓${NC} Bootstrap complete"
        fi
        ;;
    agents)
        # ── Seed/update multi-agent architecture in LibreChat ──
        # Creates all 11 agents (L1-L5 + utility) with correct tools, edges, models.
        # Requires LibreChat running + user credentials.
        #
        # Usage:
        #   augur agents                         # seed for default setup user
        #   augur agents user@example.com pass   # seed for specific user
        #   augur agents --dry-run               # preview without creating
        AGENTS_EMAIL="${2:-${AUGUR_SETUP_EMAIL:-}}"
        AGENTS_PASS="${3:-${AUGUR_SETUP_PASSWORD:-}}"

        if [[ "${2:-}" == "--dry-run" ]]; then
            "$STACK/venv/bin/python" "$STACK/librechat-uberspace/scripts/seed-agents.py" \
                --email "dummy@example.com" --password "dummy" --dry-run
        elif [[ -z "$AGENTS_EMAIL" || -z "$AGENTS_PASS" ]]; then
            echo -e "${YELLOW}Usage: augur agents <email> <password>${NC}"
            echo ""
            echo "  Seeds all 11 multi-agent architecture agents for the given user."
            echo "  Or set AUGUR_SETUP_EMAIL and AUGUR_SETUP_PASSWORD env vars."
            echo ""
            echo "  augur agents admin@example.com mypassword"
            echo "  augur agents --dry-run                      # preview only"
        else
            LC_URL="http://localhost:${LC_PORT:-3080}"
            echo -e "${CYAN}Seeding agents at ${LC_URL} for ${AGENTS_EMAIL}...${NC}"
            "$STACK/venv/bin/python" "$STACK/librechat-uberspace/scripts/seed-agents.py" \
                --email "$AGENTS_EMAIL" --password "$AGENTS_PASS" \
                --base-url "$LC_URL"
            echo -e "${GREEN}✓${NC} Agent seeding complete"
        fi
        ;;
    *)
        echo -e "${CYAN}Augur — ops shortcuts${NC}"
        echo -e "${CYAN}Host: ${UBER_HOST:-$(hostname -f 2>/dev/null || echo 'unknown')}${NC}"
        echo ""
        echo "  augur s|status     Show service status + version"
        echo "  augur r|restart    Restart LibreChat"
        echo "  augur l|logs       Tail service logs"
        echo "  augur testrun      Run LibreChat in foreground (see errors directly)"
        echo "  augur v|version    Show installed version"
        echo ""
        echo "  augur u|update     Update from latest GitHub release"
        echo "  augur pull         Quick update via git pull (dev)"
        echo "  augur install      Re-run full installer (idempotent, uses prebuilt release)"
        echo "  augur rb|rollback  Rollback to previous version"
        echo ""
        echo "  augur backup       Backup MongoDB to ~/backups/mongo/ (rolling)"
        echo "  augur restore [f]  Restore MongoDB from backup (latest if no file)"
        echo "  augur backups      List available backups"
        echo "  augur cron         Run cron hook (compact + agent invocation)"
        echo "  augur bootstrap    Bootstrap profile data via agent (MCP + search)"
        echo "  augur agents       Seed multi-agent architecture (11 agents)"
        echo "  augur check        Health check (services, config, connectivity)"
        echo "  augur check -t     Health check + run test suite (bats + pytest)"
        echo "  augur proxy ...    CLIProxyAPI (Claude Max subscription proxy)"
        echo "  augur env          Edit .env"
        echo "  augur yaml         Edit librechat.yaml"
        echo "  augur conf         Edit deploy.conf"
        echo ""
        echo "  Fresh install:"
        echo "    curl -sL https://raw.githubusercontent.com/${GH_USER}/${GH_REPO}/main/librechat-uberspace/scripts/Augur.sh | bash"
        ;;
esac
