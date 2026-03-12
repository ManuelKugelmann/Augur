#!/bin/bash
# Augur shared helpers — sourced by Augur.sh and sub-scripts
# Not meant to be executed directly.

# ── Defaults (work before repo/config exist) ──
GH_USER="${GH_USER:-ManuelKugelmann}"
GH_REPO="${GH_REPO:-Augur}"
STACK_DIR="${STACK_DIR:-$HOME/augur}"
APP_DIR="${APP_DIR:-$HOME/LibreChat}"
LC_PORT="${LC_PORT:-3080}"
NODE_VERSION="${NODE_VERSION:-22}"
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
    local python="$1" min_ver=22
    log "  → $python -m pip --version"
    local ver _pip_err
    _pip_err=$(mktemp -p "$HOME")
    ver=$(timeout 30 "$python" -m pip --version </dev/null 2>"$_pip_err" | awk '{print $2}' | cut -d. -f1)
    local rc=$?
    if [[ -s "$_pip_err" ]]; then warn "pip stderr: $(cat "$_pip_err")"; fi
    rm -f "$_pip_err"
    if (( rc != 0 )); then
        warn "pip --version exited $rc (timeout=124)"; return 1
    fi
    if [[ -z "$ver" ]]; then
        warn "pip --version returned empty output"; return 1
    fi
    if (( ver >= min_ver )); then
        log "pip $ver is recent enough (>=$min_ver), skipping upgrade"
        return 0
    fi
    log "pip $ver < $min_ver, upgrading..."
    log "  → $python -m pip install --upgrade pip"
    timeout 600 "$python" -m pip install --upgrade pip </dev/null
}

_pip_install() {
    local python="$1" req="$2"
    local constraint
    constraint=$(mktemp -p "$HOME")
    if ! _is_u8; then echo 'pandas<3' > "$constraint"; fi
    log "  → $python -m pip install --prefer-binary -c <constraint> -r $req ${*:3}"
    timeout 600 "$python" -m pip install --prefer-binary -c "$constraint" -r "$req" "${@:3}" </dev/null
    rm -f "$constraint"
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

# ── Resolve LibreChat bundle URL from GitHub Releases ──
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

# ── Download, extract, and install/update LibreChat bundle ──
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
    log "  → tar xzf $lc_tmp/bundle.tar.gz -C $lc_tmp/app"
    tar xzf "$lc_tmp/bundle.tar.gz" -C "$lc_tmp/app" -v 2>&1 | {
        _n=0
        while IFS= read -r _; do
            _n=$((_n + 1))
            (( _n % 1000 == 0 )) && printf '\r    %d files...' "$_n"
        done
        printf '\r    %d files extracted\n' "$_n"
    }
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
