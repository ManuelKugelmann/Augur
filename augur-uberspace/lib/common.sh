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

# ── Download, extract, and install/update LibreChat bundle ──
_lc_download_and_setup() {
    local skip_current=false
    [[ "${1:-}" == "--skip-if-current" ]] && skip_current=true

    _resolve_bundle_url
    [[ -z "$_BUNDLE_URL" ]] && return 1

    # Skip if asset hasn't changed (compare asset updated_at timestamp)
    if [[ "$skip_current" == true && -f "$APP/.asset_ts" ]]; then
        local installed_ts=""
        installed_ts=$(cat "$APP/.asset_ts" 2>/dev/null)
        if [[ -n "$installed_ts" && -n "$_BUNDLE_ASSET_TS" && "$installed_ts" == "$_BUNDLE_ASSET_TS" ]]; then
            log "LibreChat already up-to-date (asset unchanged since ${installed_ts})"
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

    # Store asset timestamp for next skip check
    [[ -n "$_BUNDLE_ASSET_TS" ]] && echo "$_BUNDLE_ASSET_TS" > "$APP/.asset_ts"

    return 0
}
