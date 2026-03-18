#!/bin/bash
# Augur shared helpers — sourced by Augur.sh and sub-scripts
# Not meant to be executed directly.

# ── Defaults (work before repo/config exist) ──
GH_USER="${GH_USER:-ManuelKugelmann}"
GH_REPO="${GH_REPO:-Augur}"
STACK_DIR="${STACK_DIR:-$HOME/augur}"
APP_DIR="${APP_DIR:-$HOME/LibreChat}"
LC_PORT="${LC_PORT:-3080}"
NODE_VERSION="${NODE_VERSION:-24}"
BRANCH="${BRANCH:-main}"

# ── Load central config if available ──
_augur_load_conf() {
    local _script_conf=""
    if [[ -n "${BASH_SOURCE[0]:-}" ]]; then
        _script_conf="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." 2>/dev/null && pwd)/deploy.conf"
    fi
    for _conf in "$STACK_DIR/deploy.conf" "$_script_conf"; do
        [[ -n "$_conf" ]] && [[ -f "$_conf" ]] && { source "$_conf"; break; }
    done
}
_augur_load_conf

APP="${APP_DIR:-$HOME/LibreChat}"
STACK="${STACK_DIR:-$HOME/augur}"

# ── LibreChat version from package.json (ground truth) ──
_lc_pkg_version() {
    local pkg="$APP/package.json"
    if [[ -f "$pkg" ]] && command -v node &>/dev/null; then
        node -p "require('$pkg').version" 2>/dev/null && return
    fi
    # Fallback: grep without node
    if [[ -f "$pkg" ]]; then
        grep -m1 '"version"' "$pkg" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+[^"]*' && return
    fi
    echo "unknown"
}

# ── Output helpers ──
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
die()  { echo -e "${RED}✗${NC} $1" >&2; exit 1; }

# ── Service management (systemd on U8) ──
_svc_exists()  { [[ -f "$HOME/.config/systemd/user/${1}.service" ]]; }
_svc_start()   { _svc_exists "$1" && systemctl --user start "$1"; }
_svc_stop()    { systemctl --user stop "$1" 2>/dev/null; }
_svc_restart() { _svc_exists "$1" && systemctl --user restart "$1"; }
_svc_status()  { systemctl --user status "$1" --no-pager; }
_svc_logs()    { journalctl --user -u "$1" -f; }
_svc_reload()  { systemctl --user daemon-reload || true; }

# ── Web backend ──
_web_backend() {
    local path="$1" port="$2"
    uberspace web backend add "$path" port "$port" --force
}

# ── pip install helper ──
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
    log "  → $python -m pip install -v --prefer-binary -r $req ${*:3}"
    "$python" -m pip install -v --prefer-binary -r "$req" "${@:3}" </dev/null
}

# ── HTTP helpers ──
gh_curl() {
    curl -sf "$@"
}

# Robust file download with progress and retries
_download() {
    local url="$1" out="$2" desc="${3:-file}"
    local retries=4 attempt=0 delay=2 rc=0

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

# ── Extract asset updated_at from release JSON ──
# Finds the updated_at timestamp for the asset whose download URL matches $1
_extract_asset_timestamp() {
    local url="$1" json="$2"
    # Walk through assets: find the block containing our URL, grab its updated_at
    echo "$json" | grep -F -B5 "$url" \
        | grep -o '"updated_at":[^"]*"[^"]*"' | head -1 | cut -d'"' -f4 || true
}

# ── Resolve LibreChat bundle URL from GitHub Releases ──
_resolve_bundle_url() {
    _BUNDLE_URL="" _BUNDLE_TAG="" _BUNDLE_ASSET_TS=""
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

    if [[ -n "$_BUNDLE_URL" ]]; then
        _BUNDLE_ASSET_TS=$(_extract_asset_timestamp "$_BUNDLE_URL" "$json")
        log "Found bundle: ${_BUNDLE_URL} (tag: ${_BUNDLE_TAG}, asset updated: ${_BUNDLE_ASSET_TS:-unknown})"
    fi
}

# ── Resolve MCP Nodes bundle URL from GitHub Releases ──
_resolve_mcp_nodes_url() {
    _MCP_NODES_URL="" _MCP_NODES_TAG="" _MCP_NODES_ASSET_TS=""
    local json="" api_url=""
    local tag="${MCP_NODES_TAG:-mcp-nodes-build}"

    api_url="https://api.github.com/repos/${GH_USER}/${GH_REPO}/releases/tags/${tag}"
    log "Checking MCP nodes release: ${api_url}"
    json=$(gh_curl "$api_url" 2>/dev/null) || json=""

    if [[ -n "$json" ]]; then
        _MCP_NODES_URL=$(echo "$json" | grep -oE '"browser_download_url":\s*"[^"]*mcp-nodes-build\.tar\.gz"' | head -1 | grep -oE '(https?|file)://[^"]+' || true)
        _MCP_NODES_TAG=$(echo "$json" | grep -o '"tag_name":[^"]*"[^"]*"' | cut -d'"' -f4 || true)
    fi

    if [[ -n "$_MCP_NODES_URL" ]]; then
        _MCP_NODES_ASSET_TS=$(_extract_asset_timestamp "$_MCP_NODES_URL" "$json")
        log "Found MCP nodes bundle: ${_MCP_NODES_URL} (tag: ${_MCP_NODES_TAG}, asset updated: ${_MCP_NODES_ASSET_TS:-unknown})"
    fi
}

# ── Download, extract, and install/update MCP Nodes bundle ──
_mcp_nodes_download_and_setup() {
    local skip_current=false
    [[ "${1:-}" == "--skip-if-current" ]] && skip_current=true

    _resolve_mcp_nodes_url
    [[ -z "$_MCP_NODES_URL" ]] && return 1

    local mcp_dir="$STACK/mcp-nodes"

    # Skip if asset hasn't changed (compare asset updated_at timestamp)
    if [[ "$skip_current" == true && -f "$mcp_dir/.asset_ts" ]]; then
        local installed_ts=""
        installed_ts=$(cat "$mcp_dir/.asset_ts" 2>/dev/null)
        if [[ -n "$installed_ts" && -n "$_MCP_NODES_ASSET_TS" && "$installed_ts" == "$_MCP_NODES_ASSET_TS" ]]; then
            log "MCP nodes already up-to-date (asset unchanged since ${installed_ts})"
            return 0
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

    # Store asset timestamp for next skip check
    [[ -n "$_MCP_NODES_ASSET_TS" ]] && echo "$_MCP_NODES_ASSET_TS" > "$mcp_dir/.asset_ts"

    log "MCP nodes bundle installed ($(head -1 "$mcp_dir/.version" 2>/dev/null || echo 'unknown'))"
    return 0
}

# ── Web backend with retries (install uses this) ──
_web_backend_retry() {
    local path="$1" port="$2"
    # Skip if already configured
    local existing
    existing=$(timeout 30 uberspace web backend list 2>&1 || true)
    if echo "$existing" | grep -qF "$path" && echo "$existing" | grep -q "$port"; then
        log "Web backend ${path} → port ${port} already set"
        return 0
    fi
    local attempt=0 delay=2
    while (( attempt < 3 )); do
        attempt=$((attempt + 1))
        timeout 30 uberspace web backend add "$path" port "$port" --force && return 0
        (( attempt < 3 )) && { warn "web backend ${path} attempt ${attempt}/3 timed out, retrying in ${delay}s..."; sleep "$delay"; delay=$((delay * 2)); }
    done
    return 1
}

# ── Download, extract, and install/update LibreChat bundle ──
_lc_download_and_setup() {
    local skip_current=false
    [[ "${1:-}" == "--skip-if-current" ]] && skip_current=true

    _resolve_bundle_url
    [[ -z "$_BUNDLE_URL" ]] && return 1

    # Log current installed state for diagnostics
    if [[ "$skip_current" == true ]]; then
        local _cur_ver="" _cur_ts="" _cur_tag=""
        [[ -f "$APP/.version" ]]     && _cur_ver=$(cat "$APP/.version" 2>/dev/null)
        [[ -f "$APP/.asset_ts" ]]    && _cur_ts=$(cat "$APP/.asset_ts" 2>/dev/null)
        [[ -f "$APP/.release-tag" ]] && _cur_tag=$(cat "$APP/.release-tag" 2>/dev/null)
        log "Installed: version=${_cur_ver:-?} tag=${_cur_tag:-?} asset_ts=${_cur_ts:-?}"
        log "Available: tag=${_BUNDLE_TAG:-?} asset_ts=${_BUNDLE_ASSET_TS:-?}"
    fi

    # Skip if asset hasn't changed (compare asset updated_at timestamp)
    if [[ "$skip_current" == true && -n "$_BUNDLE_ASSET_TS" ]]; then
        local installed_ts=""
        [[ -f "$APP/.asset_ts" ]] && installed_ts=$(cat "$APP/.asset_ts" 2>/dev/null)
        if [[ -n "$installed_ts" && "$installed_ts" == "$_BUNDLE_ASSET_TS" ]]; then
            log "LibreChat already up-to-date (asset unchanged since ${installed_ts})"
            return 0
        fi
        # Fallback: check release tag (written by install.sh)
        local installed_tag=""
        [[ -f "$APP/.release-tag" ]] && installed_tag=$(cat "$APP/.release-tag" 2>/dev/null)
        if [[ -n "$installed_tag" && "$installed_tag" == "$_BUNDLE_TAG" ]]; then
            log "LibreChat already up-to-date (tag ${installed_tag})"
            # Backfill .asset_ts so future checks are fast
            echo "$_BUNDLE_ASSET_TS" > "$APP/.asset_ts"
            return 0
        fi
    fi

    # Fallback: compare .version against release tag (works when asset_ts unavailable)
    if [[ "$skip_current" == true && -f "$APP/.version" && -n "$_BUNDLE_TAG" ]]; then
        local installed_ver=""
        installed_ver=$(cat "$APP/.version" 2>/dev/null)
        local tag_ver="${_BUNDLE_TAG#v}"
        if [[ -n "$installed_ver" && ( "$installed_ver" == "$tag_ver" || "$installed_ver" == "$_BUNDLE_TAG" ) ]]; then
            log "LibreChat already up-to-date (${installed_ver})"
            return 0
        fi
    fi

    # Clean up stale temp dirs from previous failed runs
    local _stale
    for _stale in "$HOME"/.lc-install.*; do
        [[ -d "$_stale" ]] && { log "Cleaning stale temp dir: $_stale"; rm -rf "$_stale"; }
    done

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
        tar -I pigz -xf "$lc_tmp/bundle.tar.gz" -C "$lc_tmp/app"
    else
        tar xzf "$lc_tmp/bundle.tar.gz" -C "$lc_tmp/app"
    fi
    # Free disk space: tarball no longer needed after extraction
    rm -f "$lc_tmp/bundle.tar.gz"
    local _nfiles
    _nfiles=$(find "$lc_tmp/app" -type f | wc -l)
    log "Extracted ${_nfiles} files"

    local bundle_ver=""
    [[ -f "$lc_tmp/app/.version" ]] && bundle_ver=$(cat "$lc_tmp/app/.version")
    [[ -z "$bundle_ver" ]] && bundle_ver="${_BUNDLE_TAG:-unknown}"

    log "LibreChat version: ${bundle_ver}"
    log "Running setup..."
    log "  → bash $STACK/augur-uberspace/scripts/setup.sh $lc_tmp/app $bundle_ver"
    bash "$STACK/augur-uberspace/scripts/setup.sh" "$lc_tmp/app" "$bundle_ver"

    # Store tracking files for next skip check (sync with install.sh)
    [[ -n "$_BUNDLE_ASSET_TS" ]] && echo "$_BUNDLE_ASSET_TS" > "$APP/.asset_ts"
    [[ -n "$_BUNDLE_TAG" ]]      && echo "$_BUNDLE_TAG"      > "$APP/.release-tag"

    # Log real version from package.json for verification
    local _real_ver
    _real_ver=$(_lc_pkg_version)
    [[ "$_real_ver" != "unknown" ]] && log "LibreChat package.json: v${_real_ver}"

    # Explicit cleanup (setup.sh mv'd contents out; remove empty temp dir)
    rm -rf "$lc_tmp"
    return 0
}

# ═══════════════════════════════════════════════
#  _update_core — shared logic for install & update
# ═══════════════════════════════════════════════
# Usage: _update_core [install|update]
#   install: clone-or-pull with fallback, create venv if missing/broken
#   update:  pull --ff-only only, skip venv creation
_update_core() {
    local mode="${1:-update}"

    # ── 1. Git pull (or clone on install) ──
    if [[ -d "$STACK/.git" ]]; then
        log "Pulling latest code..."
        if [[ "$mode" == "install" ]]; then
            timeout 120 git -C "$STACK" pull --ff-only origin "$BRANCH" </dev/null || \
                { warn "pull --ff-only failed, resetting to origin/$BRANCH"
                  timeout 120 git -C "$STACK" fetch origin "$BRANCH" </dev/null && \
                  git -C "$STACK" reset --hard "origin/$BRANCH"; } || \
                warn "git pull/fetch failed (repo may already be current)"
        else
            git -C "$STACK" pull --ff-only
        fi
        log "Repo updated"
    elif [[ "$mode" == "install" ]]; then
        log "Cloning repo..."
        timeout 120 git clone -b "$BRANCH" "https://github.com/${GH_USER}/${GH_REPO}.git" "$STACK" </dev/null
        log "Cloned → $STACK"
    else
        die "Repo not found at $STACK — run install first"
    fi

    # Re-source config after pull (deploy.conf may have changed)
    [[ -f "$STACK/deploy.conf" ]] && source "$STACK/deploy.conf"

    _INSTALL_SHA=$(git -C "$STACK" rev-parse --short HEAD 2>/dev/null || echo "unknown")
    _INSTALL_COMMIT_DATE=$(git -C "$STACK" log -1 --format='%ci' 2>/dev/null || echo "unknown")
    log "Version: ${_INSTALL_SHA} (${_INSTALL_COMMIT_DATE})"

    # ── 2. Copy augur CLI (atomic: temp+mv to avoid overwriting running script) ──
    mkdir -p "$HOME/bin"
    cp "$STACK/Augur.sh" "$HOME/bin/augur.tmp" 2>/dev/null \
        && mv -f "$HOME/bin/augur.tmp" "$HOME/bin/augur" 2>/dev/null || true
    chmod +x "$HOME/bin/augur" 2>/dev/null || true
    ln -sf "$HOME/bin/augur" "$HOME/bin/Augur" 2>/dev/null || true

    # ── 3. Copy scripts + merge librechat config ──
    # Skip if APP doesn't exist yet — fresh installs create APP via LC bundle in step 6,
    # and setup.sh handles config merge there. This step is for updates/re-installs.
    if [[ -d "$APP" ]]; then
        mkdir -p "$APP/scripts" "$APP/config"
        cp "$STACK/augur-uberspace/scripts/"*.sh "$APP/scripts/" 2>/dev/null || true
        cp "$STACK/augur-uberspace/scripts/"*.py "$APP/scripts/" 2>/dev/null || true
        local _SYS_YAML="$STACK/augur-uberspace/config/librechat-system.yaml"
        local _USR_YAML="$APP/librechat-user.yaml"
        local _MERGE_SCRIPT="$STACK/augur-uberspace/scripts/merge-librechat-yaml.py"
        if [[ -f "$_SYS_YAML" ]] && [[ -f "$_MERGE_SCRIPT" ]]; then
            # Seed user overlay from template if missing
            if [[ ! -f "$_USR_YAML" ]] && [[ -f "$STACK/augur-uberspace/config/librechat-user.yaml" ]]; then
                cp "$STACK/augur-uberspace/config/librechat-user.yaml" "$_USR_YAML" 2>/dev/null || true
            fi
            local _MERGE_PY=""
            for _py in "$STACK/venv/bin/python" python3 python; do
                command -v "$_py" &>/dev/null && "$_py" -c "import yaml" 2>/dev/null && { _MERGE_PY="$_py"; break; }
            done
            if [[ -n "$_MERGE_PY" ]] && [[ -f "$_USR_YAML" ]]; then
                # Keep .example copies next to active configs so users can diff
            cp "$_SYS_YAML" "$APP/librechat-system.yaml.example" 2>/dev/null || true
            cp "$STACK/augur-uberspace/config/librechat-user.yaml" "$APP/librechat-user.yaml.example" 2>/dev/null || true
            cp "$STACK/augur-uberspace/config/.env.example" "$APP/.env.example" 2>/dev/null || true
            # Clean up old .sample naming
            rm -f "$APP/librechat-system.yaml.sample" "$APP/librechat-user.yaml.sample" 2>/dev/null || true
            if "$_MERGE_PY" "$_MERGE_SCRIPT" "$_SYS_YAML" "$_USR_YAML" "$APP/librechat.yaml" "$HOME" 2>/dev/null; then
                    log "Merged librechat.yaml (system + user)"
                else
                    warn "Config merge failed — using system template"
                    cp "$_SYS_YAML" "$APP/librechat.yaml"
                    sed -i "s|__HOME__|$HOME|g" "$APP/librechat.yaml"
                fi
            elif [[ ! -f "$APP/librechat.yaml" ]]; then
                cp "$_SYS_YAML" "$APP/librechat.yaml"
                sed -i "s|__HOME__|$HOME|g" "$APP/librechat.yaml"
            fi
        elif [[ ! -f "$APP/librechat.yaml" ]] && [[ -f "$STACK/augur-uberspace/config/librechat-system.yaml" ]]; then
            cp "$STACK/augur-uberspace/config/librechat-system.yaml" "$APP/librechat.yaml"
            sed -i "s|__HOME__|$HOME|g" "$APP/librechat.yaml"
        fi
    fi

    # ── 4. Python venv ──
    local PYTHON_BIN=""
    for _py in "python${PYTHON_VERSION:-}" python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
        [[ -z "$_py" || "$_py" == "python" ]] && continue
        if command -v "$_py" &>/dev/null && \
           "$_py" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
            PYTHON_BIN="$_py"; break
        fi
    done

    if [[ -d "$STACK/venv" ]]; then
        local _venv_check
        if ! _venv_check=$(timeout 10 "$STACK/venv/bin/python" -c 'import sys; print(sys.version)' </dev/null 2>&1); then
            warn "Venv python is broken or stale. Output: $_venv_check"
            if [[ "$mode" == "install" ]]; then
                warn "Recreating venv..."
                rm -rf "$STACK/venv"
            else
                warn "Run 'augur install' to recreate venv"
            fi
        else
            log "Python venv OK, checking pip..."
            if ! _pip_upgrade "$STACK/venv/bin/python"; then
                if [[ "$mode" == "install" ]]; then
                    warn "pip check failed, recreating venv..."
                    rm -rf "$STACK/venv"
                else
                    warn "pip check failed — run 'augur install' to recreate venv"
                fi
            fi
        fi
    fi

    if [[ ! -d "$STACK/venv" ]]; then
        if [[ "$mode" != "install" ]]; then
            warn "Python venv not found at $STACK/venv — run 'augur install' first"
            return 0
        fi
        [[ -z "$PYTHON_BIN" ]] && die "Python 3.10+ not found. Check: python3 --version"
        log "Creating Python venv..."
        "$PYTHON_BIN" -m venv --without-pip "$STACK/venv"
        log "Bootstrapping pip inside venv..."
        "$STACK/venv/bin/python" -m ensurepip </dev/null || die "ensurepip failed"
        _pip_upgrade "$STACK/venv/bin/python" || die "pip upgrade failed"
    fi

    # ── 5. Install Python requirements (skip if unchanged) ──
    if [[ -d "$STACK/venv" ]]; then
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
    fi

    # ── 6. LibreChat bundle ──
    if ! _lc_download_and_setup --skip-if-current; then
        if [[ "$mode" == "install" ]]; then
            die "No prebuilt LibreChat release found. Create one via: Actions → Release LibreChat Bundle → Run workflow"
        else
            warn "LibreChat bundle download failed"
        fi
    fi

    # ── 7. MCP Node servers ──
    log "Checking MCP Node servers bundle..."
    if ! _mcp_nodes_download_and_setup --skip-if-current; then
        warn "MCP Node servers bundle not found — Node MCPs won't be available"
    fi

    # ── 8. Augur News site repo ──
    local _NEWS_DIR="${AUGUR_SITE_DIR:-$HOME/augur.news}"
    local _NEWS_BRANCH="${AUGUR_SITE_BRANCH:-augur_news}"
    local _NEWS_REMOTE="https://github.com/${GH_USER}/${GH_REPO}.git"
    if [[ -d "$_NEWS_DIR/.git" ]]; then
        log "Pulling Augur News site (${_NEWS_BRANCH})..."
        timeout 120 git -C "$_NEWS_DIR" pull --ff-only origin "$_NEWS_BRANCH" </dev/null 2>/dev/null \
            || warn "News site pull failed (may already be current)"
    else
        log "Cloning Augur News site → $_NEWS_DIR (branch: ${_NEWS_BRANCH})..."
        if timeout 120 git clone -b "$_NEWS_BRANCH" "$_NEWS_REMOTE" "$_NEWS_DIR" </dev/null 2>/dev/null; then
            log "News site cloned"
        else
            # Branch may not exist yet — create an orphan checkout
            log "Branch '$_NEWS_BRANCH' not found, creating orphan checkout..."
            mkdir -p "$_NEWS_DIR"
            git -C "$_NEWS_DIR" init </dev/null
            git -C "$_NEWS_DIR" remote add origin "$_NEWS_REMOTE" 2>/dev/null || true
            git -C "$_NEWS_DIR" checkout --orphan "$_NEWS_BRANCH" </dev/null
            mkdir -p "$_NEWS_DIR/_posts" "$_NEWS_DIR/assets/images" "$_NEWS_DIR/_data"
            log "News site initialized (orphan branch: $_NEWS_BRANCH)"
        fi
    fi

    # ── 9. Clean up stale config backups ──
    for _bak in "$APP"/librechat.yaml.bak.* "$APP"/librechat.yaml.pre-safe.bak.*; do
        [[ -f "$_bak" ]] && { rm -f "$_bak"; log "Removed stale backup: $(basename "$_bak")"; }
    done

    # ── 10. Clean up legacy trading.service ──
    if [[ -f "$HOME/.config/systemd/user/trading.service" ]]; then
        log "Removing legacy trading.service (renamed to augur)..."
        systemctl --user stop trading 2>/dev/null || true
        systemctl --user disable trading 2>/dev/null || true
        rm -f "$HOME/.config/systemd/user/trading.service"
        _svc_reload
    fi
}
