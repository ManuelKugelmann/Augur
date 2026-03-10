#!/bin/bash
# LibreChat Lite bootstrap — curl | bash to install or update
set -euo pipefail

# ── Load central config ──
for conf in "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/deploy.conf" \
            "$HOME/assist/deploy.conf"; do
    [[ -f "$conf" ]] && { source "$conf"; break; }
done

REPO="${LIBRECHAT_REPO:-${GH_USER:-ManuelKugelmann}/${GH_REPO:-TradingAssistant}}"
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
die()  { echo -e "${RED}✗${NC} $1" >&2; exit 1; }

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

    while (( attempt < retries )); do
        attempt=$((attempt + 1))
        rc=0
        if command -v wget &>/dev/null; then
            wget --progress=dot:mega --timeout=30 --tries=1 \
                 -O "$out" "$url" 2>&1 \
                | grep -E --line-buffered '^\s+[0-9]|saved' \
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

echo -e "${CYAN}═══════════════════════════════════════${NC}"
echo -e "${CYAN} LibreChat Lite → ${UBER_HOST:-Uberspace}${NC}"
echo -e "${CYAN}═══════════════════════════════════════${NC}"
echo ""

# Resolve release: RELEASE_TAG="" → latest, "prerelease" → newest, else specific tag
JSON=""
if [[ -z "${RELEASE_TAG:-}" ]]; then
    log "Fetching latest release from ${REPO}..."
    JSON=$(gh_curl "https://api.github.com/repos/${REPO}/releases/latest") || die "Failed to fetch release info"
elif [[ "${RELEASE_TAG}" == "prerelease" ]]; then
    log "Fetching newest release (incl. prereleases) from ${REPO}..."
    RAW=$(gh_curl "https://api.github.com/repos/${REPO}/releases?per_page=1") || die "Failed to fetch releases"
    JSON=$(echo "$RAW" | sed -n 's/^\[//;s/\]$//;p' | head -1)
else
    log "Fetching release ${RELEASE_TAG} from ${REPO}..."
    JSON=$(gh_curl "https://api.github.com/repos/${REPO}/releases/tags/${RELEASE_TAG}") || die "Failed to fetch release ${RELEASE_TAG}"
fi

# Match both librechat-bundle.tar.gz (CI workflow) and librechat-build.tar.gz (manual)
URL=$(echo "$JSON" | grep -oE '"browser_download_url":\s*"[^"]*librechat-(bundle|build)\.tar\.gz"' | head -1 | grep -oE 'https://[^"]+' || true)
VER=$(echo "$JSON" | grep -o '"tag_name":[^"]*"[^"]*"' | cut -d'"' -f4)

# /releases/latest only returns non-prerelease releases, but librechat-build.yml
# marks all builds as prerelease. Fall back to the rolling "librechat-build" tag.
if [[ -z "$URL" && -z "${RELEASE_TAG:-}" ]]; then
    log "No bundle in latest release, trying librechat-build tag..."
    JSON=$(gh_curl "https://api.github.com/repos/${REPO}/releases/tags/librechat-build" 2>/dev/null) || JSON=""
    if [[ -n "$JSON" ]]; then
        URL=$(echo "$JSON" | grep -oE '"browser_download_url":\s*"[^"]*librechat-(bundle|build)\.tar\.gz"' | head -1 | grep -oE 'https://[^"]+' || true)
        VER=$(echo "$JSON" | grep -o '"tag_name":[^"]*"[^"]*"' | cut -d'"' -f4)
    fi
fi

[[ -z "$URL" ]] && die "No bundle found in release"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

log "Downloading ${VER}..."
_download "$URL" "$TMP/bundle.tar.gz" "LibreChat ${VER}"

log "Extracting..."
mkdir -p "$TMP/app"
tar xzf "$TMP/bundle.tar.gz" -C "$TMP/app"

exec bash "$TMP/app/scripts/setup.sh" "$TMP/app" "$VER"
