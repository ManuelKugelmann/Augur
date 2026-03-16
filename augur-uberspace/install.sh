#!/bin/bash
# Augur installer — self-contained bootstrap, works via curl|bash
#
# Fresh install:
#   curl -sL "https://raw.githubusercontent.com/ManuelKugelmann/Augur/main/augur-uberspace/install.sh?$(date +%s)" | bash
#
# Re-run (idempotent):
#   augur install
#
# This script only bootstraps the repo clone, then delegates to Augur.sh install
# which shares all logic with augur update via common.sh _update_core.

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
BRANCH="${BRANCH:-main}"

STACK="${STACK_DIR:-$HOME/augur}"

# ── Output helpers ──
RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${GREEN}✓${NC} $1"; }
die()  { echo -e "${RED}✗${NC} $1" >&2; exit 1; }

# ── Load config if available (re-run from cloned repo) ──
[[ -f "$STACK/deploy.conf" ]] && source "$STACK/deploy.conf"

# ── Bootstrap: clone or update repo so Augur.sh exists ──
if [[ -d "$STACK/.git" ]]; then
    log "Repo exists at $STACK, pulling latest..."
    timeout 120 git -C "$STACK" pull --ff-only origin "$BRANCH" </dev/null || \
        { log "  → pull failed, fetching + resetting..."
          timeout 120 git -C "$STACK" fetch origin "$BRANCH" </dev/null && \
          git -C "$STACK" reset --hard "origin/$BRANCH"; }
    log "Repo updated"
else
    log "Cloning repo..."
    timeout 120 git clone -b "$BRANCH" "https://github.com/${GH_USER}/${GH_REPO}.git" "$STACK" </dev/null
    log "Cloned → $STACK"
fi

# ── Delegate to Augur.sh install ──
[[ -f "$STACK/Augur.sh" ]] || die "Augur.sh not found at $STACK after clone"
exec bash "$STACK/Augur.sh" install "$@"
}
_main "$@"
