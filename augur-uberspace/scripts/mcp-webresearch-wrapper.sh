#!/usr/bin/env bash
# Wrapper for @mzxrai/mcp-webresearch MCP server.
# Filters the harmless ENOENT cleanup error on shutdown
# (upstream bug: rmdir on already-removed temp screenshots dir).
set -uo pipefail

PACKAGE="@mzxrai/mcp-webresearch"
MCP_DIR="$HOME/augur/mcp-nodes"

# Resolve the installed entry point
ENTRY="$MCP_DIR/node_modules/.bin/mcp-webresearch"
if [[ ! -x "$ENTRY" ]]; then
    # Fallback: find the dist/index.js directly
    ENTRY="$MCP_DIR/node_modules/$PACKAGE/dist/index.js"
    if [[ ! -f "$ENTRY" ]]; then
        echo "mcp-webresearch not installed in $MCP_DIR — run: cd $MCP_DIR && npm install $PACKAGE" >&2
        exit 1
    fi
    exec node "$ENTRY" "$@" 2> >(grep -v 'ENOENT.*mcp-screenshots' >&2)
fi

exec "$ENTRY" "$@" 2> >(grep -v 'ENOENT.*mcp-screenshots' >&2)
