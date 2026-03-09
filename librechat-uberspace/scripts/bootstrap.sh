#!/bin/bash
# LibreChat Lite bootstrap — curl | bash to install or update
set -euo pipefail

# ── Load central config ──
for conf in "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/deploy.conf" \
            "$HOME/mcps/deploy.conf"; do
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
[[ -z "$URL" ]] && die "No bundle found in release"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

log "Downloading ${VER}..."
gh_curl -L -o "$TMP/bundle.tar.gz" "$URL"

log "Extracting..."
mkdir -p "$TMP/app"
tar xzf "$TMP/bundle.tar.gz" -C "$TMP/app"

exec bash "$TMP/app/scripts/setup.sh" "$TMP/app" "$VER"
