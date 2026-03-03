#!/bin/bash
# LibreChat ops shortcuts — usage: lc [command]
set -euo pipefail

# ── Load central config ──
for conf in "$HOME/mcp-signals-stack/deploy.conf" \
            "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." 2>/dev/null && pwd)/deploy.conf"; do
    [[ -f "$conf" ]] && { source "$conf"; break; }
done

APP="${APP_DIR:-$HOME/LibreChat}"
DATA="${DATA_DIR:-$HOME/librechat-data}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

case "${1:-help}" in
    s|status)
        supervisorctl status librechat
        echo -e "${CYAN}Version:${NC} $(cat "$APP/.version" 2>/dev/null || echo 'unknown')"
        echo -e "${CYAN}Host:${NC} ${UBER_HOST:-$(hostname -f 2>/dev/null || echo 'unknown')}"
        ;;
    r|restart)
        supervisorctl restart librechat
        echo -e "${GREEN}✓${NC} Restarted"
        ;;
    l|logs)
        supervisorctl tail -f librechat
        ;;
    v|version)
        cat "$APP/.version" 2>/dev/null || echo "unknown"
        ;;
    u|update)
        echo -e "${CYAN}Pulling latest release...${NC}"
        bash "$APP/scripts/bootstrap.sh"
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
    sync)
        if [[ -d "$DATA/.git" ]]; then
            cd "$DATA"
            git add -A
            if ! git diff --cached --quiet; then
                git commit -m "sync $(date -Is)"
                git push
                echo -e "${GREEN}✓${NC} Data synced to GitHub"
            else
                echo -e "${YELLOW}⚠${NC} No changes to sync"
            fi
        else
            echo -e "${RED}✗${NC} Data repo not initialized. Run: bash $APP/scripts/setup-data-repo.sh"
        fi
        ;;
    env)
        ${EDITOR:-nano} "$APP/.env"
        ;;
    yaml)
        ${EDITOR:-nano} "$APP/librechat.yaml"
        ;;
    conf)
        ${EDITOR:-nano} "$HOME/mcp-signals-stack/deploy.conf"
        ;;
    *)
        echo -e "${CYAN}LibreChat Lite — ops shortcuts${NC}"
        echo -e "${CYAN}Host: ${UBER_HOST:-$(hostname -f 2>/dev/null || echo 'unknown')}${NC}"
        echo ""
        echo "  lc s|status     Show service status + version"
        echo "  lc r|restart    Restart LibreChat"
        echo "  lc l|logs       Tail service logs"
        echo "  lc v|version    Show installed version"
        echo "  lc u|update     Pull + install latest release"
        echo "  lc rb|rollback  Rollback to previous version"
        echo "  lc sync         Force git sync of data dir"
        echo "  lc env          Edit .env"
        echo "  lc yaml         Edit librechat.yaml"
        echo "  lc conf         Edit deploy.conf"
        ;;
esac
