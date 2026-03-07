#!/usr/bin/env bash
# Auth health monitor for claude mcp serve tokens.
# Checks expiry passively and validates with a live probe.
# Sends ntfy notification on any failure.
#
# Usage:
#   claude-auth-daemon.sh --once    # single check (for cron)
#   claude-auth-daemon.sh           # loop every 30 min
set -euo pipefail

# Source env for CLAUDE_CODE_OAUTH_TOKEN and NOTIFY_URL
if [[ -f ~/mcps/.env ]]; then
    set -a; source ~/mcps/.env; set +a
fi

WARN_DAYS=${CLAUDE_WARN_DAYS:-30}
CREDS=~/.claude/.credentials.json

check_expiry() {
    [[ -f "$CREDS" ]] || return 0
    exp=$(python3 -c "import json,sys; d=json.load(open('$CREDS')); print(d.get('expiresAt',''))" 2>/dev/null) || return 0
    [[ -z "$exp" ]] && return 0
    now=$(date +%s)
    exp_s=$(date -d "$exp" +%s 2>/dev/null || date -j -f "%Y-%m-%dT%H:%M:%SZ" "$exp" +%s)
    days_left=$(( (exp_s - now) / 86400 ))
    if (( days_left < 0 )); then
        curl -sd "Claude token EXPIRED on $(hostname)" "${NOTIFY_URL:-}" 2>/dev/null || true
        exit 1
    elif (( days_left < WARN_DAYS )); then
        curl -sd "Claude token expires in ${days_left}d on $(hostname)" "${NOTIFY_URL:-}" 2>/dev/null || true
    fi
}

check_live() {
    output=$(CLAUDE_CODE_OAUTH_TOKEN="${CLAUDE_CODE_OAUTH_TOKEN:-}" claude -p "echo ok" 2>&1) || true
    if echo "$output" | grep -qiE "authentication_error|401|token has expired|unauthorized"; then
        curl -sd "Claude auth failure on $(hostname): $output" "${NOTIFY_URL:-}" 2>/dev/null || true
        exit 1
    fi
}

check_expiry
if [[ "${1:-}" == "--once" ]]; then
    check_live
else
    while true; do check_live; sleep 1800; done
fi
