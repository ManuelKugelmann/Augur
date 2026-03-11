#!/bin/bash
# Augur ops — command router for daily operations
#
# Fresh install (one-liner):
#   curl -sL "https://raw.githubusercontent.com/ManuelKugelmann/Augur/main/augur-uberspace/install.sh?$(date +%s)" | bash
#
# After install:
#   augur help              # show all commands
#   augur install           # re-run full installer (idempotent)
#
# Installed as ~/bin/augur and ~/bin/Augur

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

# ── Source shared helpers ──
# Try repo-relative path first (when running from ~/bin/augur → ~/augur/Augur.sh)
_AUGUR_DIR="${STACK_DIR:-$HOME/augur}"
_COMMON="$_AUGUR_DIR/augur-uberspace/lib/common.sh"
if [[ ! -f "$_COMMON" ]]; then
    # Fallback: try relative to script location
    _SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)"
    _COMMON="$_SCRIPT_DIR/augur-uberspace/lib/common.sh"
fi
if [[ -f "$_COMMON" ]]; then
    source "$_COMMON"
else
    # Minimal fallback (should not happen after install)
    GH_USER="${GH_USER:-ManuelKugelmann}"
    GH_REPO="${GH_REPO:-Augur}"
    STACK="${STACK_DIR:-$HOME/augur}"
    APP="${APP_DIR:-$HOME/LibreChat}"
    RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
    log()  { echo -e "${GREEN}✓${NC} $1"; }
    warn() { echo -e "${YELLOW}⚠${NC} $1"; }
    die()  { echo -e "${RED}✗${NC} $1" >&2; exit 1; }
    _is_u8() { [[ -f /etc/arch-release ]]; }
fi

# ── Command dispatch ──
CMD="${1:-help}"

case "$CMD" in
    install)
        # Delegate to standalone installer
        bash "$STACK/augur-uberspace/install.sh" "${@:2}"
        ;;
    s|status)
        _svc_status librechat || echo "librechat: not registered"
        _svc_status trading || true
        _svc_status charts || true
        echo -e "${CYAN}Version:${NC} $(cat "$APP/.version" 2>/dev/null || echo 'unknown')"
        echo -e "${CYAN}Host:${NC} ${UBER_HOST:-$(hostname -f 2>/dev/null || echo 'unknown')}"
        echo -e "${CYAN}Platform:${NC} $(_is_u8 && echo 'U8 (Arch/systemd)' || echo 'U7 (CentOS/supervisord)')"
        ;;
    r|restart)
        _svc_restart librechat || die "Failed to restart librechat"
        _svc_restart trading || true
        echo -e "${GREEN}✓${NC} Restarted (librechat + trading)"
        ;;
    l|logs)
        _svc_logs librechat || die "Failed to tail logs (is librechat registered?)"
        ;;
    testrun)
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
        echo -e "${CYAN}Dev update via git pull...${NC}"
        git -C "$STACK" pull --ff-only
        VER="dev-$(git -C "$STACK" rev-parse --short HEAD)"
        mkdir -p "$APP/scripts" "$APP/config"
        cp "$STACK/augur-uberspace/scripts/"*.sh "$APP/scripts/" 2>/dev/null || true
        if [[ -f "$STACK/augur-uberspace/config/librechat.yaml" ]] && [[ ! -f "$APP/librechat.yaml" ]]; then
            cp "$STACK/augur-uberspace/config/librechat.yaml" "$APP/librechat.yaml"
            sed -i "s|__HOME__|$HOME|g" "$APP/librechat.yaml"
        fi
        cp "$STACK/Augur.sh" "$HOME/bin/augur" 2>/dev/null || true
        chmod +x "$HOME/bin/augur" 2>/dev/null || true
        ln -sf "$HOME/bin/augur" "$HOME/bin/Augur" 2>/dev/null || true
        if [[ -d "$STACK/venv" ]]; then
            _pip_upgrade "$STACK/venv/bin/python" \
                || die "pip upgrade failed or timed out"
            log "Installing Python requirements..."
            _pip_install "$STACK/venv/bin/python" "$STACK/requirements.txt" \
                || die "pip install requirements failed or timed out"
        else
            warn "Python venv not found at $STACK/venv — run 'augur install' first"
        fi
        echo "$VER" > "$APP/.version"
        _svc_restart librechat || true
        _svc_restart trading || true
        echo -e "${GREEN}✓${NC} Updated to ${VER} via git pull"
        ;;
    rb|rollback)
        if [[ ! -d "${APP}.prev" ]]; then
            die "No previous version to rollback to"
        fi
        _svc_stop librechat || warn "Could not stop librechat (may not be running)"
        rm -rf "$APP"
        mv "${APP}.prev" "$APP"
        _svc_start librechat || warn "Could not start librechat after rollback"
        echo -e "${GREEN}✓${NC} Rolled back to $(cat "$APP/.version" 2>/dev/null || echo 'unknown')"
        ;;
    backup)
        [[ -f "$STACK/venv/bin/python" ]] || die "Python venv not found. Run: augur install"
        STACK="$STACK" "$STACK/venv/bin/python" "$STACK/scripts/mongo-backup.py" backup
        ;;
    restore)
        [[ -f "$STACK/venv/bin/python" ]] || die "Python venv not found. Run: augur install"
        STACK="$STACK" "$STACK/venv/bin/python" "$STACK/scripts/mongo-backup.py" restore "${2:-}"
        ;;
    backups)
        [[ -f "$STACK/venv/bin/python" ]] || die "Python venv not found. Run: augur install"
        STACK="$STACK" "$STACK/venv/bin/python" "$STACK/scripts/mongo-backup.py" list
        ;;
    cron)
        # Unified cron hook (every 15 min)
        HOUR=$(date +%H)
        MIN=$(date +%M)
        DOW=$(date +%u)
        _cron_log() { echo "[augur-cron] $1"; }

        # Daily at 02:00 UTC: compact + backup
        if [[ "$HOUR" == "02" ]]; then
            sleep "$((RANDOM % 300))"
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

            _cron_log "running daily backup"
            if [[ -f "$STACK/venv/bin/python" ]] && [[ -f "$STACK/scripts/mongo-backup.py" ]]; then
                STACK="$STACK" "$STACK/venv/bin/python" "$STACK/scripts/mongo-backup.py" backup 2>&1 \
                    | while read -r line; do _cron_log "backup: $line"; done
            fi
        fi

        # Every 30 min: Claude token health check
        if [[ -f "$HOME/.claude-auth.env" ]] && [[ "$((10#$MIN % 30))" -eq 0 ]]; then
            if [[ -x "$HOME/bin/claude-auth-daemon.sh" ]]; then
                "$HOME/bin/claude-auth-daemon.sh" --once 2>&1 | while read -r line; do _cron_log "$line"; done
            fi
        fi

        # Every 6 hours: invoke cron-planner agent
        if [[ "$((10#$HOUR % 6))" -eq 0 ]] && [[ "$((10#$MIN))" -lt 15 ]]; then
            sleep "$((RANDOM % 180))"
            if [[ -n "${AUGUR_AGENTS_API_KEY:-}" ]]; then
                LC_URL="http://localhost:${LC_PORT:-3080}"
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
                if ! command -v cliproxyapi &>/dev/null; then
                    log "Installing CLIProxyAPI..."
                    npm install -g cliproxyapi
                fi
                log "CLIProxyAPI $(cliproxyapi --version 2>/dev/null || echo 'installed')"
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
                if [[ ! -f "$PROXY_AUTH" ]]; then
                    warn "No token found at $PROXY_AUTH"
                    echo "  Run on a machine with a browser:"
                    echo "    claude setup-token"
                    echo "  Then save the token:"
                    echo "    echo 'CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-...' > $PROXY_AUTH"
                    echo "    chmod 600 $PROXY_AUTH"
                fi
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
                cp "$STACK/augur-uberspace/scripts/claude-auth-daemon.sh" "$HOME/bin/claude-auth-daemon.sh" 2>/dev/null || true
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
                _svc_start cliproxyapi || die "Failed to start cliproxyapi"
                log "CLIProxyAPI started"
                ;;
            stop)
                _svc_stop cliproxyapi || die "Failed to stop cliproxyapi"
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
        PASS=0; FAIL=0; WARN=0; TOTAL=0
        _ok()   { PASS=$((PASS+1)); TOTAL=$((TOTAL+1)); echo -e "  ${GREEN}PASS${NC}  $1"; }
        _fail() { FAIL=$((FAIL+1)); TOTAL=$((TOTAL+1)); echo -e "  ${RED}FAIL${NC}  $1"; }
        _warn() { WARN=$((WARN+1)); TOTAL=$((TOTAL+1)); echo -e "  ${YELLOW}WARN${NC}  $1"; }
        _skip() { TOTAL=$((TOTAL+1)); echo -e "  ${CYAN}SKIP${NC}  $1"; }

        echo -e "${CYAN}── Health Check ──${NC}"
        echo ""
        [[ -d "$STACK/.git" ]] && _ok "Stack repo exists at $STACK" || _fail "Stack repo missing at $STACK"
        [[ -f "$STACK/deploy.conf" ]] && _ok "deploy.conf present" || _fail "deploy.conf missing"
        [[ -x "$STACK/venv/bin/python" ]] && _ok "Python venv: $("$STACK/venv/bin/python" --version 2>&1)" || _fail "Python venv missing at $STACK/venv"
        if [[ -x "$STACK/venv/bin/python" ]]; then
            "$STACK/venv/bin/python" -c "import fastmcp, httpx, pymongo, dotenv" 2>/dev/null \
                && _ok "Python deps: fastmcp, httpx, pymongo, dotenv" \
                || _fail "Python deps: missing"
        fi
        if command -v node &>/dev/null; then
            NODE_VER="$(node -v 2>/dev/null)"; NODE_MAJOR="${NODE_VER#v}"; NODE_MAJOR="${NODE_MAJOR%%.*}"
            [[ "$NODE_MAJOR" -ge 20 ]] && _ok "Node.js ${NODE_VER}" || _warn "Node.js ${NODE_VER} (recommend >= 20)"
        else _fail "Node.js not found"; fi
        [[ -f "$APP/.version" ]] && _ok "LibreChat installed: $(cat "$APP/.version")" || _fail "LibreChat not installed at $APP"
        if [[ -f "$APP/.env" ]]; then
            grep -q "MONGO_URI=" "$APP/.env" 2>/dev/null && _ok "LibreChat .env with MONGO_URI" || _warn "LibreChat .env exists but MONGO_URI not set"
        else _fail "LibreChat .env missing"; fi
        if [[ -f "$APP/librechat.yaml" ]]; then
            grep -q "mcpServers:" "$APP/librechat.yaml" 2>/dev/null && _ok "librechat.yaml with MCP servers" || _warn "librechat.yaml exists but no mcpServers section"
        else _fail "librechat.yaml missing"; fi
        [[ -f "$STACK/.env" ]] && _ok "Signals .env present" || _warn "Signals .env missing (optional)"

        echo ""; echo -e "${CYAN}── Services ($(_is_u8 && echo 'systemd' || echo 'supervisord')) ──${NC}"; echo ""
        for svc in librechat trading charts cliproxyapi; do
            if _is_u8; then
                if systemctl --user is-active "$svc" &>/dev/null; then _ok "$svc: RUNNING"
                elif systemctl --user is-enabled "$svc" &>/dev/null; then _warn "$svc: STOPPED (enabled)"
                elif [[ -f "$HOME/.config/systemd/user/${svc}.service" ]]; then _warn "$svc: STOPPED"
                else _skip "$svc: not registered"; fi
            else
                SVC_STATUS="$(supervisorctl status "$svc" 2>/dev/null || true)"
                if [[ -z "$SVC_STATUS" ]]; then _skip "$svc: not registered"
                elif echo "$SVC_STATUS" | grep -q "RUNNING"; then _ok "$svc: RUNNING"
                elif echo "$SVC_STATUS" | grep -q "STOPPED"; then _warn "$svc: STOPPED"
                else _fail "$svc: $(echo "$SVC_STATUS" | head -1)"; fi
            fi
        done

        echo ""; echo -e "${CYAN}── Web Backends ──${NC}"; echo ""
        if command -v uberspace &>/dev/null; then
            WB_LIST="$(uberspace web backend list 2>/dev/null || true)"
            if [[ -n "$WB_LIST" ]]; then
                echo "$WB_LIST" | while read -r line; do echo -e "  ${CYAN}│${NC} $line"; done
                echo "$WB_LIST" | grep -q "${LC_PORT:-3080}" && _ok "Web backend: / → port ${LC_PORT:-3080}" || _warn "Web backend: / not routed to port ${LC_PORT:-3080}"
                echo "$WB_LIST" | grep -q "8066" && _ok "Web backend: /charts → port 8066" || _warn "Web backend: /charts not routed to port 8066"
            else _warn "Web backends: could not list"; fi
        else _skip "Web backends: uberspace CLI not available"; fi

        echo ""; echo -e "${CYAN}── Connectivity ──${NC}"; echo ""
        LC_CODE="$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:${LC_PORT:-3080}/" 2>/dev/null || echo "000")"
        if [[ "$LC_CODE" == "200" ]] || [[ "$LC_CODE" == "301" ]] || [[ "$LC_CODE" == "302" ]]; then _ok "LibreChat HTTP: ${LC_CODE} on port ${LC_PORT:-3080}"
        elif [[ "$LC_CODE" == "000" ]]; then _fail "LibreChat HTTP: not reachable on port ${LC_PORT:-3080}"
        else _warn "LibreChat HTTP: ${LC_CODE} on port ${LC_PORT:-3080}"; fi
        CHARTS_CODE="$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:8066/charts/" 2>/dev/null || echo "000")"
        [[ "$CHARTS_CODE" != "000" ]] && _ok "Charts HTTP: ${CHARTS_CODE} on port 8066" || _warn "Charts HTTP: not reachable on port 8066"
        PROXY_PORT="${CLIPROXY_PORT:-8317}"
        if [[ -f "$HOME/.claude-auth.env" ]] || [[ -f "$HOME/etc/services.d/cliproxyapi.ini" ]] || [[ -f "$HOME/.config/systemd/user/cliproxyapi.service" ]]; then
            PROXY_CODE="$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:${PROXY_PORT}/v1/models" 2>/dev/null || echo "000")"
            if [[ "$PROXY_CODE" == "200" ]]; then _ok "CLIProxyAPI: OK on port ${PROXY_PORT}"
            elif [[ "$PROXY_CODE" == "401" ]]; then _fail "CLIProxyAPI: 401 — token expired"
            elif [[ "$PROXY_CODE" == "000" ]]; then _fail "CLIProxyAPI: not reachable on port ${PROXY_PORT}"
            else _warn "CLIProxyAPI: HTTP ${PROXY_CODE} on port ${PROXY_PORT}"; fi
        else _skip "CLIProxyAPI: not configured"; fi

        echo ""; echo -e "${CYAN}── Data ──${NC}"; echo ""
        if [[ -d "$STACK/profiles" ]]; then
            PROFILE_COUNT="$(find "$STACK/profiles" -name '*.json' -not -name 'INDEX_*' -not -path '*/SCHEMAS/*' 2>/dev/null | wc -l)"
            [[ "$PROFILE_COUNT" -gt 0 ]] && _ok "Profiles: ${PROFILE_COUNT} JSON files" || _warn "Profiles: directory exists but no profiles found"
        else _fail "Profiles directory missing"; fi
        crontab -l 2>/dev/null | grep -q "augur cron" && _ok "Cron: augur cron scheduled" || _warn "Cron: augur cron not scheduled (run: crontab -e)"
        SYNTAX_OK=true
        for script in "$STACK/augur-uberspace/scripts/"*.sh; do
            if ! bash -n "$script" 2>/dev/null; then _fail "Syntax error: $(basename "$script")"; SYNTAX_OK=false; fi
        done
        [[ "$SYNTAX_OK" == true ]] && _ok "Shell scripts: all pass syntax check"

        if [[ "${2:-}" == "--test" ]] || [[ "${2:-}" == "-t" ]]; then
            echo ""; echo -e "${CYAN}── Test Suite ──${NC}"; echo ""
            if command -v bats &>/dev/null && [[ -d "$STACK/tests" ]]; then
                BATS_FILES=()
                for f in "$STACK/tests/"*.bats; do
                    [[ "$(basename "$f")" == "test_uberspace.bats" ]] && [[ "$(hostname -f 2>/dev/null)" != *".uber.space" ]] && continue
                    BATS_FILES+=("$f")
                done
                if [[ ${#BATS_FILES[@]} -gt 0 ]]; then
                    bats "${BATS_FILES[@]}" 2>&1 && _ok "Bats tests: all passed" || _fail "Bats tests: some failures"
                fi
            else
                ! command -v bats &>/dev/null && _skip "Bats tests: bats not installed" || _skip "Bats tests: no tests found"
            fi
            if [[ -x "$STACK/venv/bin/python" ]] && "$STACK/venv/bin/python" -c "import pytest" 2>/dev/null; then
                "$STACK/venv/bin/python" -m pytest "$STACK/tests/test_store.py" -q 2>&1 && _ok "Pytest: all passed" || _fail "Pytest: some failures"
            else _skip "Pytest: not installed"; fi
            if [[ -f "$STACK/tests/test_uberspace.bats" ]] && [[ "$(hostname -f 2>/dev/null)" == *".uber.space" ]]; then
                echo ""; echo -e "${CYAN}── Uberspace Live Tests ──${NC}"; echo ""
                bats "$STACK/tests/test_uberspace.bats" 2>&1 && _ok "Uberspace tests: all passed" || _fail "Uberspace tests: some failures"
            fi
        fi

        echo ""; echo -e "${CYAN}── Summary ──${NC}"; echo ""
        echo -e "  Total: ${TOTAL}   ${GREEN}Pass: ${PASS}${NC}   ${RED}Fail: ${FAIL}${NC}   ${YELLOW}Warn: ${WARN}${NC}"
        echo ""
        if [[ "${2:-}" != "--test" ]] && [[ "${2:-}" != "-t" ]]; then
            echo -e "  ${CYAN}Tip:${NC} augur check --test"; echo ""
        fi
        if [[ "$FAIL" -gt 0 ]]; then echo -e "  ${RED}Some checks failed.${NC}"; exit 1
        elif [[ "$WARN" -gt 0 ]]; then echo -e "  ${YELLOW}All critical checks passed, some warnings.${NC}"
        else echo -e "  ${GREEN}All checks passed!${NC}"; fi
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
        BOOTSTRAP_API_KEY="${AUGUR_AGENTS_API_KEY:-}"
        BOOTSTRAP_AGENT_ID="${AUGUR_BOOTSTRAP_AGENT_ID:-}"
        if [[ "${2:-}" == "--dry-run" ]]; then
            "$STACK/venv/bin/python" "$STACK/augur-uberspace/scripts/bootstrap-data.py" --dry-run "${@:3}"
        elif [[ -z "$BOOTSTRAP_API_KEY" ]]; then
            echo -e "${YELLOW}Usage: augur bootstrap [--kind KIND] [--batch-size N] [--dry-run]${NC}"
            echo ""; echo "  Required env vars: AUGUR_AGENTS_API_KEY, AUGUR_BOOTSTRAP_AGENT_ID"
            echo ""; echo "  augur bootstrap --kind countries  # one kind"
            echo "  augur bootstrap --dry-run          # preview only"
        else
            LC_URL="http://localhost:${LC_PORT:-3080}"
            echo -e "${CYAN}Bootstrapping profiles via ${LC_URL}...${NC}"
            "$STACK/venv/bin/python" "$STACK/augur-uberspace/scripts/bootstrap-data.py" \
                --api-key "$BOOTSTRAP_API_KEY" --agent-id "$BOOTSTRAP_AGENT_ID" --base-url "$LC_URL" "${@:2}"
            echo -e "${GREEN}✓${NC} Bootstrap complete"
        fi
        ;;
    agents)
        AGENTS_EMAIL="${2:-${AUGUR_SETUP_EMAIL:-}}"
        AGENTS_PASS="${3:-${AUGUR_SETUP_PASSWORD:-}}"
        if [[ "${2:-}" == "--dry-run" ]]; then
            "$STACK/venv/bin/python" "$STACK/augur-uberspace/scripts/seed-agents.py" \
                --email "dummy@example.com" --password "dummy" --dry-run
        elif [[ -z "$AGENTS_EMAIL" || -z "$AGENTS_PASS" ]]; then
            echo -e "${YELLOW}Usage: augur agents <email> <password>${NC}"
            echo ""; echo "  augur agents admin@example.com mypassword"
            echo "  augur agents --dry-run  # preview only"
        else
            LC_URL="http://localhost:${LC_PORT:-3080}"
            echo -e "${CYAN}Seeding agents at ${LC_URL} for ${AGENTS_EMAIL}...${NC}"
            "$STACK/venv/bin/python" "$STACK/augur-uberspace/scripts/seed-agents.py" \
                --email "$AGENTS_EMAIL" --password "$AGENTS_PASS" --base-url "$LC_URL"
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
        echo "  augur install      Re-run full installer (idempotent)"
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
        echo "    curl -sL \"https://raw.githubusercontent.com/${GH_USER}/${GH_REPO}/main/augur-uberspace/install.sh?\$(date +%s)\" | bash"
        ;;
esac
}
_main "$@"
