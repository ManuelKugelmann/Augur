#!/usr/bin/env bash
# Ensure at least one Jekyll article exists so the site builds.
# Usage: ensure-placeholder.sh <site-dir> [preview]
set -euo pipefail

SITE_DIR="${1:?Usage: ensure-placeholder.sh <site-dir> [preview]}"
PREVIEW="${2:-}"

if find "$SITE_DIR/_posts" -name '*.md' ! -name 'README*' | grep -q .; then
  echo "Posts found, no placeholder needed"
  exit 0
fi

DATE=$(date -u +%Y-%m-%d)
TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)

mkdir -p "$SITE_DIR/_posts/the.augur/days"

if [ "$PREVIEW" = "preview" ]; then
  SLUG="welcome-preview"
  HEADLINE="Welcome to Augur News — Preview"
  TAGS="[placeholder, preview]"
  SIGNAL="This is a preview deployment of Augur News from a pull request."
  EXTRAPOLATION="Theme and layout changes from the PR are rendered here for review."
  IN_THE_WORKS="Merge the PR to see changes on the production site."
else
  SLUG="welcome"
  HEADLINE="Welcome to Augur News"
  TAGS="[placeholder]"
  SIGNAL="Augur News is live. Articles generated from trading signals will appear here."
  EXTRAPOLATION="This placeholder confirms the Jekyll deployment pipeline is working end-to-end."
  IN_THE_WORKS="Live signal-driven articles are coming soon."
fi

cat > "$SITE_DIR/_posts/the.augur/days/${DATE}-${SLUG}.md" <<EOF
---
layout: article
brand: the
horizon: days
categories: the.augur/days
date: ${DATE}
headline: "${HEADLINE}"
created_at: "${TIMESTAMP}"
tags: ${TAGS}
sources: []
model: placeholder
---

## The Signal

${SIGNAL}

## The Extrapolation

${EXTRAPOLATION}

## In The Works

${IN_THE_WORKS}
EOF

echo "Created placeholder article: ${DATE}-${SLUG}.md"
