#!/bin/bash
# TradeAssistant ops — single entry point for install + daily ops
#
# Fresh install (one-liner, downloads prebuilt LibreChat from GitHub Release):
#   curl -sL https://raw.githubusercontent.com/ManuelKugelmann/TradingAssistant/main/librechat-uberspace/scripts/TradeAssistant.sh | bash
#
# After install:
#   ta help              # show all commands
#   ta install           # re-run full installer (idempotent)
#
# Installed as ~/bin/ta (shorthand) and ~/bin/TradeAssistant
set -euo pipefail

# ── Defaults (work before repo/config exist) ──
# These defaults are needed for the curl|bash one-liner where deploy.conf
# doesn't exist yet.  Once the repo is cloned, deploy.conf is sourced below
# and its values take effect for all subsequent variable expansions.
GH_USER="${GH_USER:-ManuelKugelmann}"
GH_REPO="${GH_REPO:-TradingAssistant}"
STACK_DIR="${STACK_DIR:-$HOME/mcps}"
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
STACK="${STACK_DIR:-$HOME/mcps}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
die()  { echo -e "${RED}✗${NC} $1" >&2; exit 1; }

# ── Auto-detect: piped with no args → install ──
CMD="${1:-help}"
if [[ "$CMD" == "help" ]] && ! [[ -d "$STACK/.git" ]]; then
    CMD="install"
fi

# ═══════════════════════════════════════════════
#  install — full install/update (idempotent)
#    ta install           → prebuilt release bundle from GitHub Releases
# ═══════════════════════════════════════════════
_do_install() {
    # Track whether .env files are new (need editing)
    local NEED_STACK_ENV=false
    local NEED_APP_ENV=false

    echo -e "${CYAN}══════════════════════════════════════════${NC}"
    echo -e "${CYAN} TradingAssistant + LibreChat → Uberspace ${NC}"
    echo -e "${CYAN}══════════════════════════════════════════${NC}"
    echo ""

    gh_curl() {
        curl -sf "$@"
    }

    # ── 1. Node.js ──────────────────────────────
    log "Setting Node.js ${NODE_VERSION}..."
    uberspace tools version use node "$NODE_VERSION" || warn "Failed to set Node.js version via uberspace CLI"
    command -v node &>/dev/null || die "Node.js not available"
    log "Node.js $(node -v)"

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
    for _py in "python${PYTHON_VERSION:-}" python3.13 python3.12 python3.11 python3.10 python3; do
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
        "$STACK/venv/bin/pip" install -q --upgrade pip 2>/dev/null || true
        "$STACK/venv/bin/pip" install -q -r "$STACK/requirements.txt" 2>/dev/null || true
    else
        log "Creating Python venv..."
        "$PYTHON_BIN" -m venv "$STACK/venv"
        "$STACK/venv/bin/pip" install -q --upgrade pip
        "$STACK/venv/bin/pip" install -q -r "$STACK/requirements.txt"
    fi
    log "Python venv ready"

    # ── 4. Signals stack .env ───────────────────
    if [[ ! -f "$STACK/.env" ]]; then
        cp "$STACK/.env.example" "$STACK/.env"
        NEED_STACK_ENV=true
        log "Created $STACK/.env (needs configuration)"
    else
        log "Signals .env already exists"
    fi

    # ── 5. Register supervisord services ────────
    log "Registering services..."
    mkdir -p ~/etc/services.d ~/logs

    # trading: combined MCP server (store + 12 domains) via streamable-http
    # LibreChat connects to localhost:8071/mcp and injects per-user headers.
    # Uses bash -c to source .env (which may contain MongoDB URIs with special chars)
    # so we don't need to escape values for supervisord's environment= syntax.
    cat > ~/etc/services.d/trading.ini << SVCEOF
[program:trading]
directory=${STACK}
command=bash -c 'set -a; [ -f ${STACK}/.env ] && . ${STACK}/.env; set +a; export MCP_TRANSPORT=http MCP_PORT=8071 PROFILES_DIR=${STACK}/profiles; exec ${STACK}/venv/bin/python src/servers/combined_server.py'
autostart=true
autorestart=true
startsecs=10
SVCEOF

    # charts: HTTP chart server, runs independently of LibreChat
    cat > ~/etc/services.d/charts.ini << SVCEOF
[program:charts]
directory=${STACK}
command=${STACK}/venv/bin/python src/store/charts.py
autostart=true
autorestart=true
startsecs=60
SVCEOF
    # Register /charts route to chart server port
    uberspace web backend set /charts --http --port 8066 || warn "Failed to set /charts web backend"
    log "Services registered (trading, charts)"

    # ── 6. LibreChat — download prebuilt release bundle ──
    #       Bundle is a vanilla LibreChat build, versioned by LC's package.json + commit.
    local NEED_LC_SETUP=false
    local LC_TMP=""

    # Fetch release info from GitHub
    # RELEASE_TAG="" → /releases/latest (production)
    # RELEASE_TAG="prerelease" → newest prerelease
    # RELEASE_TAG="v0.1.0" or "dev-abc1234" → specific tag
    local RELEASE_URL="" RELEASE_JSON="" BUNDLE_URL=""
    if [[ -z "${RELEASE_TAG:-}" ]]; then
        RELEASE_URL="https://api.github.com/repos/${GH_USER}/${GH_REPO}/releases/latest"
        RELEASE_JSON=$(gh_curl "$RELEASE_URL" 2>/dev/null) || RELEASE_JSON=""
    elif [[ "${RELEASE_TAG}" == "prerelease" ]]; then
        # Pick the first (newest) release, which includes prereleases
        RELEASE_JSON=$(gh_curl "https://api.github.com/repos/${GH_USER}/${GH_REPO}/releases?per_page=1" 2>/dev/null) || RELEASE_JSON=""
        # API returns an array for /releases, extract first element
        RELEASE_JSON=$(echo "$RELEASE_JSON" | sed -n 's/^\[//;s/\]$//;p' | head -1)
    else
        RELEASE_URL="https://api.github.com/repos/${GH_USER}/${GH_REPO}/releases/tags/${RELEASE_TAG}"
        RELEASE_JSON=$(gh_curl "$RELEASE_URL" 2>/dev/null) || RELEASE_JSON=""
    fi
    if [[ -n "$RELEASE_JSON" ]]; then
        # Match both librechat-bundle.tar.gz (CI workflow) and librechat-build.tar.gz (manual)
        BUNDLE_URL=$(echo "$RELEASE_JSON" | grep -oE '"browser_download_url":\s*"[^"]*librechat-(bundle|build)\.tar\.gz"' | head -1 | grep -oE 'https://[^"]+' || true)
    fi

    # Current installed version (LibreChat version, e.g. "1.6.1+abc1234")
    local INSTALLED_VER=""
    [[ -f "$APP/.version" ]] && INSTALLED_VER=$(cat "$APP/.version")

    if [[ -d "$APP" ]] && [[ -n "$INSTALLED_VER" ]]; then
        if [[ -z "$BUNDLE_URL" ]]; then
            log "LibreChat installed (${INSTALLED_VER}), no release info available"
        else
            # Download bundle to temp, check .version inside before deciding
            LC_TMP=$(mktemp -d)
            trap 'rm -rf "${LC_TMP:-}"' EXIT

            gh_curl -L -o "$LC_TMP/bundle.tar.gz" "$BUNDLE_URL"
            mkdir -p "$LC_TMP/app"
            tar xzf "$LC_TMP/bundle.tar.gz" -C "$LC_TMP/app"

            local BUNDLE_VER=""
            [[ -f "$LC_TMP/app/.version" ]] && BUNDLE_VER=$(cat "$LC_TMP/app/.version")

            if [[ "$INSTALLED_VER" == "$BUNDLE_VER" ]]; then
                log "LibreChat already up-to-date (${INSTALLED_VER})"
                rm -rf "$LC_TMP"; LC_TMP=""
            else
                NEED_LC_SETUP=true
                [[ ! -f "$APP/.env" ]] && NEED_APP_ENV=true
                log "Updating LibreChat ${INSTALLED_VER} → ${BUNDLE_VER}..."
                bash "$STACK/librechat-uberspace/scripts/setup.sh" "$LC_TMP/app" "$BUNDLE_VER"
            fi
        fi
    elif [[ -n "$BUNDLE_URL" ]]; then
        # Fresh install — download bundle
        NEED_LC_SETUP=true
        NEED_APP_ENV=true

        LC_TMP=$(mktemp -d)
        trap 'rm -rf "${LC_TMP:-}"' EXIT

        log "Downloading LibreChat release..."
        gh_curl -L -o "$LC_TMP/bundle.tar.gz" "$BUNDLE_URL"
        mkdir -p "$LC_TMP/app"
        tar xzf "$LC_TMP/bundle.tar.gz" -C "$LC_TMP/app"

        local VER=""
        [[ -f "$LC_TMP/app/.version" ]] && VER=$(cat "$LC_TMP/app/.version")
        [[ -z "$VER" ]] && VER="unknown"
        log "LibreChat version: ${VER}"

        bash "$STACK/librechat-uberspace/scripts/setup.sh" "$LC_TMP/app" "$VER"
    else
        die "No prebuilt LibreChat release found. Create one via: Actions → Release LibreChat Bundle → Run workflow (or: git tag v0.x.0 && git push --tags)"
    fi

    if [[ "$NEED_LC_SETUP" == false ]]; then
        # Even on re-run, ensure supervisord + web backend are configured
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
        uberspace web backend set / --http --port "${LC_PORT}" || warn "Failed to set web backend on port ${LC_PORT}"
    fi

    # ── 8. Install ta shortcut ──────────────────
    mkdir -p "$HOME/bin"
    cp "$STACK/librechat-uberspace/scripts/TradeAssistant.sh" "$HOME/bin/ta" 2>/dev/null || true
    chmod +x "$HOME/bin/ta" 2>/dev/null || true
    ln -sf "$HOME/bin/ta" "$HOME/bin/TradeAssistant" 2>/dev/null || true

    # ── 9. Reload supervisord ──────────────────
    supervisorctl reread 2>/dev/null || true
    supervisorctl update 2>/dev/null || true

    # ── 11. Auto-seed agents (if credentials available) ──
    if [[ -n "${TA_SETUP_EMAIL:-}" ]] && [[ -n "${TA_SETUP_PASSWORD:-}" ]]; then
        # Wait for LibreChat to become ready
        local LC_URL="http://localhost:${LC_PORT:-3080}"
        local LC_READY=false
        supervisorctl start librechat 2>/dev/null || true
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
                --email "$TA_SETUP_EMAIL" --password "$TA_SETUP_PASSWORD" \
                --base-url "$LC_URL" 2>&1 || warn "Agent seeding failed (seed manually: ta agents)"
        else
            warn "LibreChat not ready after 60s — seed agents manually: ta agents <email> <password>"
        fi
    fi

    # ── 12. Seed profile data into MongoDB (no overwrites) ──
    if [[ -x "$STACK/venv/bin/python" ]]; then
        log "Seeding profiles from disk into MongoDB..."
        PROFILES_DIR="$STACK/profiles" MONGO_URI_SIGNALS="${MONGO_URI_SIGNALS:-}" \
        "$STACK/venv/bin/python" -c "
import sys, os
sys.path.insert(0, os.path.join('$STACK', 'src', 'store'))
from dotenv import load_dotenv
load_dotenv(os.path.join('$STACK', '.env'))
try:
    from server import seed_profiles
    result = seed_profiles()
    if 'error' in result:
        print(f'Seed skipped: {result[\"error\"]}')
    else:
        total_seeded = sum(v.get('seeded', 0) for v in result.values())
        total_skipped = sum(v.get('skipped', 0) for v in result.values())
        print(f'Profiles seeded: {total_seeded} new, {total_skipped} existing (kept)')
        for kind, counts in sorted(result.items()):
            print(f'  {kind}: {counts[\"seeded\"]} seeded, {counts[\"skipped\"]} skipped')
except Exception as e:
    print(f'Seed skipped: {e}')
" 2>&1 | while read -r line; do log "$line"; done
    fi

    # ── 13. Bootstrap profile data via agent (if credentials available) ──
    if [[ -n "${TA_AGENTS_API_KEY:-}" ]] && [[ -n "${TA_BOOTSTRAP_AGENT_ID:-}" ]]; then
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
                --api-key "$TA_AGENTS_API_KEY" \
                --agent-id "$TA_BOOTSTRAP_AGENT_ID" \
                --base-url "$LC_URL" \
                --timeseries 2>&1 | while read -r line; do log "bootstrap: $line"; done \
                || warn "Bootstrap failed (run manually: ta bootstrap)"
        else
            warn "LibreChat not ready — run bootstrap manually: ta bootstrap"
        fi
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
            echo "    # Set ANTHROPIC_API_KEY=sk-ant-...  and/or  OPENAI_API_KEY=sk-..."
            echo ""
        fi
    fi

    echo -e "  ${CYAN}Start:${NC}"
    echo "    supervisorctl start librechat"
    echo ""
    echo -e "  ${CYAN}Access:${NC}"
    echo "    https://${UBER}"
    echo "    (first user to register becomes admin)"
    echo ""
    echo -e "  ${CYAN}Seed agents:${NC} (after first login)"
    echo "    ta agents you@example.com yourpassword"
    echo "    ta agents --dry-run        # preview only"
    echo ""
    echo -e "  ${CYAN}Ops:${NC}"
    echo "    ta help                    # all commands"
    echo "    ta pull                    # quick git-pull update (dev)"
    echo "    ta u                       # release update (prod)"
    echo ""
}

# ═══════════════════════════════════════════════
#  Command dispatch
# ═══════════════════════════════════════════════
case "$CMD" in
    s|status)
        supervisorctl status librechat 2>/dev/null || echo "librechat: not registered"
        supervisorctl status trading 2>/dev/null || true
        supervisorctl status charts 2>/dev/null || true
        echo -e "${CYAN}Version:${NC} $(cat "$APP/.version" 2>/dev/null || echo 'unknown')"
        echo -e "${CYAN}Host:${NC} ${UBER_HOST:-$(hostname -f 2>/dev/null || echo 'unknown')}"
        ;;
    r|restart)
        supervisorctl restart librechat
        supervisorctl restart trading 2>/dev/null || true
        echo -e "${GREEN}✓${NC} Restarted (librechat + trading)"
        ;;
    l|logs)
        supervisorctl tail -f librechat
        ;;
    v|version)
        cat "$APP/.version" 2>/dev/null || echo "unknown"
        ;;
    u|update)
        echo -e "${CYAN}Pulling latest release...${NC}"
        bash "$STACK/librechat-uberspace/scripts/bootstrap.sh"
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

        # Update ta/TradeAssistant shortcuts
        cp "$STACK/librechat-uberspace/scripts/TradeAssistant.sh" "$HOME/bin/ta" 2>/dev/null || true
        chmod +x "$HOME/bin/ta" 2>/dev/null || true
        ln -sf "$HOME/bin/ta" "$HOME/bin/TradeAssistant" 2>/dev/null || true

        # Update Python deps if changed
        if [[ -d "$STACK/venv" ]]; then
            "$STACK/venv/bin/pip" install -q --upgrade pip 2>/dev/null || true
            "$STACK/venv/bin/pip" install -q -r "$STACK/requirements.txt" 2>/dev/null || true
        else
            warn "Python venv not found at $STACK/venv — run 'ta install' first"
        fi

        echo "$VER" > "$APP/.version"
        supervisorctl restart librechat 2>/dev/null || true
        supervisorctl restart trading 2>/dev/null || true
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
        supervisorctl stop librechat
        rm -rf "$APP"
        mv "${APP}.prev" "$APP"
        supervisorctl start librechat
        echo -e "${GREEN}✓${NC} Rolled back to $(cat "$APP/.version" 2>/dev/null || echo 'unknown')"
        ;;
    backup)
        if [[ -f "$STACK/venv/bin/python" ]]; then
            STACK="$STACK" "$STACK/venv/bin/python" "$STACK/scripts/mongo-backup.py" backup
        else
            echo -e "${RED}✗${NC} Python venv not found. Run: ta install"
            exit 1
        fi
        ;;
    restore)
        if [[ -f "$STACK/venv/bin/python" ]]; then
            STACK="$STACK" "$STACK/venv/bin/python" "$STACK/scripts/mongo-backup.py" restore "${2:-}"
        else
            echo -e "${RED}✗${NC} Python venv not found. Run: ta install"
            exit 1
        fi
        ;;
    backups)
        if [[ -f "$STACK/venv/bin/python" ]]; then
            STACK="$STACK" "$STACK/venv/bin/python" "$STACK/scripts/mongo-backup.py" list
        else
            echo -e "${RED}✗${NC} Python venv not found. Run: ta install"
            exit 1
        fi
        ;;
    cron)
        # ── Unified cron hook (every 15 min) ─────────────────────
        # Install: crontab -e → */15 * * * * ~/bin/ta cron 2>&1 | logger -t ta-cron
        # Internally gates tasks by interval so only one cron entry is needed.
        HOUR=$(date +%H)
        MIN=$(date +%M)
        DOW=$(date +%u)   # 1=Mon .. 7=Sun

        _cron_log() { echo "[ta-cron] $1"; }

        # Random jitter (0–90s) so cron tasks don't all fire at exact :00/:15/:30/:45
        _jitter() { sleep "$((RANDOM % 90))"; }

        # ── Every 15 min: profile auto-commit ──
        _jitter
        if [[ -d "$STACK/.git" ]]; then
            cd "$STACK"
            git add -A profiles/
            if ! git diff --cached --quiet; then
                git commit -m "auto: $(date +%Y-%m-%d) profile updates"
                _cron_log "profiles committed"
            fi
            cd - >/dev/null
        fi

        # ── Daily at 02:00 UTC: compact old snapshots to archive ──
        if [[ "$HOUR" == "02" ]]; then
            sleep "$((RANDOM % 300))"   # 0–5 min extra jitter for daily tasks
            _cron_log "running daily compact"
            if [[ -f "$STACK/venv/bin/python" ]]; then
                STACK="$STACK" "$STACK/venv/bin/python" - <<'PYEOF'
import os, sys
stack = os.environ.get("STACK", os.path.expanduser("~/mcps"))
sys.path.insert(0, os.path.join(stack, "src", "store"))
sys.path.insert(0, os.path.join(stack, "src", "servers"))
from dotenv import load_dotenv
load_dotenv(os.path.join(stack, ".env"))
from server import compact, _snap_col, VALID_KINDS

for kind in VALID_KINDS:
    try:
        col = _snap_col(kind)
    except Exception as e:
        print(f"[ta-cron] compact skip {kind}: {e}")
        continue
    pipeline = [
        {"$group": {"_id": {"entity": "$meta.entity", "type": "$meta.type"}}},
    ]
    try:
        combos = list(col.aggregate(pipeline))
    except Exception as e:
        print(f"[ta-cron] compact skip {kind}: {e}")
        continue
    for c in combos:
        eid = c["_id"]["entity"]
        etype = c["_id"]["type"]
        result = compact(kind, eid, etype, older_than_days=90, bucket="month")
        status = result.get("status", "error")
        if status == "ok":
            print(f"[ta-cron] compacted {kind}/{eid}/{etype}: {result['buckets_created']} buckets, {result['snapshots_deleted']} removed")
        elif status != "nothing_to_compact":
            print(f"[ta-cron] compact {kind}/{eid}/{etype}: {status}")
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

        # ── Agent dispatcher: fetch agent list once, invoke all due agents ──
        if [[ -n "${TA_AGENTS_API_KEY:-}" ]] && [[ -f "$STACK/venv/bin/python" ]]; then
            sleep "$((RANDOM % 180))"   # 0–3 min jitter for agent calls
            LC_URL="http://localhost:${LC_PORT:-3080}"
            "$STACK/venv/bin/python" - "$LC_URL" "$TA_AGENTS_API_KEY" "$HOUR" "$MIN" <<'PYEOF' 2>&1 \
                | while read -r line; do _cron_log "agents: $line"; done
import httpx, json, sys

lc_url, api_key, hour, minute = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

# ── Dispatch table: (name_match, due_check, message, timeout) ──
DISPATCH = [
    ("cron-planner",
     lambda h, m: h % 6 == 0 and m < 15,
     "Execute your periodic routine: "
     "1) Read plans (store_get_notes kind=plan). "
     "2) Check risk status. "
     "3) For watched entities, refresh data via data agents. "
     "4) Run analysis if data is stale. "
     "5) Update plans with results. "
     "6) Log summary as event.",
     300),
    ("news-the-augur",      lambda h, m: True,
     "Check augur_due_now() and produce any due articles.", 600),
    ("news-der-augur",      lambda h, m: True,
     "Check augur_due_now() and produce any due articles.", 600),
    ("news-financial-augur", lambda h, m: True,
     "Check augur_due_now() and produce any due articles.", 600),
    ("news-finanz-augur",   lambda h, m: True,
     "Check augur_due_now() and produce any due articles.", 600),
]

# Fetch agent list once
try:
    r = httpx.get(f"{lc_url}/api/agents/v1/models",
                  headers=headers, timeout=10)
    if r.status_code != 200:
        print(f"ERROR: agent list {r.status_code}", file=sys.stderr); sys.exit(1)
    agents = {m["id"]: m for m in r.json().get("data", [])}
except Exception as e:
    print(f"ERROR: {e}", file=sys.stderr); sys.exit(1)

# Build name→id lookup (match by substring in id or name)
def find_agent(name_match):
    for aid, m in agents.items():
        if name_match in aid.lower() or name_match in m.get("name", "").lower():
            return aid
    return None

# Invoke due agents
invoked = 0
for name_match, due_check, message, timeout in DISPATCH:
    if not due_check(hour, minute):
        continue
    agent_id = find_agent(name_match)
    if not agent_id:
        print(f"SKIP {name_match}: agent not found")
        continue
    print(f"invoking {name_match} ({agent_id})")
    try:
        r = httpx.post(f"{lc_url}/api/agents/v1/chat/completions",
                       headers=headers,
                       json={"model": agent_id,
                             "messages": [{"role": "user", "content": message}],
                             "stream": False},
                       timeout=timeout)
        if r.status_code == 200:
            content = r.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            print(f"OK {name_match}: {content[:200]}")
        else:
            print(f"ERROR {name_match}: {r.status_code} {r.text[:200]}", file=sys.stderr)
    except Exception as e:
        print(f"ERROR {name_match}: {e}", file=sys.stderr)
    invoked += 1

print(f"done: {invoked} agents invoked")
PYEOF
        fi

        # ── Weekly on Sunday at 03:00 UTC: placeholder for future tasks ──
        # if [[ "$HOUR" == "03" ]] && [[ "$DOW" == "7" ]]; then
        #     _cron_log "weekly maintenance"
        # fi

        _cron_log "done (hour=$HOUR dow=$DOW)"
        ;;
    proxy)
        PROXY_PORT="${CLIPROXY_PORT:-8317}"
        PROXY_CONFIG="$HOME/.cli-proxy-api/config.yaml"
        PROXY_AUTH="$HOME/.claude-auth.env"
        PROXY_SVC="$HOME/etc/services.d/cliproxyapi.ini"
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

                # Register supervisord service
                mkdir -p "$(dirname "$PROXY_SVC")"
                cat > "$PROXY_SVC" << SVCEOF
[program:cliproxyapi]
directory=${HOME}
command=cliproxyapi --config ${PROXY_CONFIG}
environment=HOME="${HOME}"
autostart=true
autorestart=true
startsecs=10
SVCEOF
                # Append EnvironmentFile equivalent via env sourcing
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
                fi
                supervisorctl reread 2>/dev/null || true
                supervisorctl update 2>/dev/null || true
                log "Service registered (cliproxyapi)"

                # Install auth daemon
                cp "$STACK/librechat-uberspace/scripts/claude-auth-daemon.sh" "$HOME/bin/claude-auth-daemon.sh" 2>/dev/null || true
                chmod +x "$HOME/bin/claude-auth-daemon.sh" 2>/dev/null || true

                log "CLIProxyAPI setup complete"
                echo ""
                echo "  Next steps:"
                echo "    1. Add your token to $PROXY_AUTH (if not done)"
                echo "    2. ta proxy start"
                echo "    3. ta proxy test"
                echo "    4. Uncomment 'Claude Max' endpoint in librechat.yaml: ta yaml"
                echo "    5. ta restart"
                ;;
            start)
                supervisorctl start cliproxyapi
                log "CLIProxyAPI started"
                ;;
            stop)
                supervisorctl stop cliproxyapi
                log "CLIProxyAPI stopped"
                ;;
            status)
                supervisorctl status cliproxyapi 2>/dev/null || echo "cliproxyapi: not registered"
                ;;
            test)
                echo -e "${CYAN}Testing proxy at localhost:${PROXY_PORT}...${NC}"
                HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:${PROXY_PORT}/v1/models" 2>/dev/null || echo "000")
                if [[ "$HTTP_CODE" == "200" ]]; then
                    log "Proxy OK (HTTP 200)"
                    curl -s "http://localhost:${PROXY_PORT}/v1/models" | head -20
                elif [[ "$HTTP_CODE" == "000" ]]; then
                    die "Proxy not reachable. Run: ta proxy start"
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
                echo "  ta proxy setup    Install CLIProxyAPI + register service"
                echo "  ta proxy start    Start CLIProxyAPI"
                echo "  ta proxy stop     Stop CLIProxyAPI"
                echo "  ta proxy status   Show CLIProxyAPI status"
                echo "  ta proxy test     Test proxy endpoint"
                echo "  ta proxy token    Show token info"
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

        # 10. Supervisord services
        echo ""
        echo -e "${CYAN}── Services ──${NC}"
        echo ""
        for svc in librechat trading charts cliproxyapi; do
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
        done

        # 12. Web backend (LibreChat HTTP)
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
        if [[ -f "$HOME/.claude-auth.env" ]] || [[ -f "$HOME/etc/services.d/cliproxyapi.ini" ]]; then
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
        if crontab -l 2>/dev/null | grep -q "ta cron"; then
            _ok "Cron: ta cron scheduled"
        else
            _warn "Cron: ta cron not scheduled (run: crontab -e)"
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

        # 18. Run test suite if available and requested (ta check --test)
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
            echo "    ta check --test"
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
        #   ta bootstrap                              # bootstrap all kinds
        #   ta bootstrap --kind countries             # bootstrap one kind
        #   ta bootstrap --batch-size 5               # smaller batches
        #   ta bootstrap --dry-run                    # preview prompts only
        #
        # Env vars: TA_AGENTS_API_KEY, TA_BOOTSTRAP_AGENT_ID
        BOOTSTRAP_API_KEY="${TA_AGENTS_API_KEY:-}"
        BOOTSTRAP_AGENT_ID="${TA_BOOTSTRAP_AGENT_ID:-}"

        if [[ "${2:-}" == "--dry-run" ]]; then
            "$STACK/venv/bin/python" "$STACK/librechat-uberspace/scripts/bootstrap-data.py" \
                --dry-run "${@:3}"
        elif [[ -z "$BOOTSTRAP_API_KEY" ]]; then
            echo -e "${YELLOW}Usage: ta bootstrap [--kind KIND] [--batch-size N] [--dry-run]${NC}"
            echo ""
            echo "  Bootstraps profile data via LibreChat Agents API."
            echo "  Enriches existing profiles and creates new ones using MCP tools."
            echo ""
            echo "  Required env vars:"
            echo "    TA_AGENTS_API_KEY        LibreChat Agents API key"
            echo "    TA_BOOTSTRAP_AGENT_ID    Agent ID (e.g. from 'ta agents' output)"
            echo ""
            echo "  ta bootstrap                        # all kinds"
            echo "  ta bootstrap --kind countries        # one kind"
            echo "  ta bootstrap --dry-run               # preview only"
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
        #   ta agents                         # seed for default setup user
        #   ta agents user@example.com pass   # seed for specific user
        #   ta agents --dry-run               # preview without creating
        AGENTS_EMAIL="${2:-${TA_SETUP_EMAIL:-}}"
        AGENTS_PASS="${3:-${TA_SETUP_PASSWORD:-}}"

        if [[ "${2:-}" == "--dry-run" ]]; then
            "$STACK/venv/bin/python" "$STACK/librechat-uberspace/scripts/seed-agents.py" \
                --email "dummy@example.com" --password "dummy" --dry-run
        elif [[ -z "$AGENTS_EMAIL" || -z "$AGENTS_PASS" ]]; then
            echo -e "${YELLOW}Usage: ta agents <email> <password>${NC}"
            echo ""
            echo "  Seeds all 11 multi-agent architecture agents for the given user."
            echo "  Or set TA_SETUP_EMAIL and TA_SETUP_PASSWORD env vars."
            echo ""
            echo "  ta agents admin@example.com mypassword"
            echo "  ta agents --dry-run                      # preview only"
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
        echo -e "${CYAN}TradeAssistant — ops shortcuts${NC}"
        echo -e "${CYAN}Host: ${UBER_HOST:-$(hostname -f 2>/dev/null || echo 'unknown')}${NC}"
        echo ""
        echo "  ta s|status     Show service status + version"
        echo "  ta r|restart    Restart LibreChat"
        echo "  ta l|logs       Tail service logs"
        echo "  ta v|version    Show installed version"
        echo ""
        echo "  ta u|update     Update from latest GitHub release"
        echo "  ta pull         Quick update via git pull (dev)"
        echo "  ta install      Re-run full installer (idempotent, uses prebuilt release)"
        echo "  ta rb|rollback  Rollback to previous version"
        echo ""
        echo "  ta backup       Backup MongoDB to ~/backups/mongo/ (rolling)"
        echo "  ta restore [f]  Restore MongoDB from backup (latest if no file)"
        echo "  ta backups      List available backups"
        echo "  ta cron         Run cron hook (profiles + compact + agent invocation)"
        echo "  ta bootstrap    Bootstrap profile data via agent (MCP + search)"
        echo "  ta agents       Seed multi-agent architecture (11 agents)"
        echo "  ta check        Health check (services, config, connectivity)"
        echo "  ta check -t     Health check + run test suite (bats + pytest)"
        echo "  ta proxy ...    CLIProxyAPI (Claude Max subscription proxy)"
        echo "  ta env          Edit .env"
        echo "  ta yaml         Edit librechat.yaml"
        echo "  ta conf         Edit deploy.conf"
        echo ""
        echo "  Fresh install:"
        echo "    curl -sL https://raw.githubusercontent.com/${GH_USER}/${GH_REPO}/main/librechat-uberspace/scripts/TradeAssistant.sh | bash"
        ;;
esac
