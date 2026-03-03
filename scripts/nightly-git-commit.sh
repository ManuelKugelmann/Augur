#!/bin/bash
# nightly-git-commit.sh — Auto-commit profile changes
# Add to crontab: 0 2 * * * ~/mcp-signals-stack/scripts/nightly-git-commit.sh
set -euo pipefail

cd "$(dirname "$0")/.."

git add profiles/ -A
if ! git diff --cached --quiet; then
  git commit -m "auto: $(date +%Y-%m-%d) profile updates"
  echo "✅ Committed profile changes"
else
  echo "— No profile changes"
fi
