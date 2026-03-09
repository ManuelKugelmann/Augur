# The Augur — Project Specification

Automated AI-powered speculative content platform. OSINT signals → LLM extrapolation → generative images → multi-brand publication → social distribution. This document is the single source of truth for Claude Code implementation.

## Concept

The Augur is not news. It is a Nostradamus-style prediction engine that:

- Collects real OSINT signals from multiple sources
- Extrapolates plausible near-future scenarios via LLM
- Illustrates predictions with AI-generated images
- Publishes as an auto-refreshing, classic newspaper-style website
- Auto-posts shareable cards to social media with link-back to source
- Archives every prediction permanently with outcome tracking

### Editorial Voice

> "Show the storm. Point to the shelter."

Every prediction follows a three-part structure:

| Section | Purpose | Tone |
|---------|---------|------|
| ⚡ The Signal | What's actually happening right now | Factual, uncomfortable, sourced |
| 🔮 The Extrapolation | Where this leads if unchecked | Wake-up call, not sensationalism |
| 🛠️ In The Works | Who's working on solutions | Real efforts, named, sourced — not hopium |

- NOT overly optimistic — these are wake-up signals
- Solutions mentioned must be real, concrete, sourced
- If no credible solution exists, say so
- Never fabricate utopia — find the genuinely constructive thread in real signals

### LLM Prompt Framing

System prompt core directive:

> "You are a clear-eyed analyst. Lead with the problem. Don't soften it. Then identify real, concrete, sourced efforts addressing it. Never fabricate solutions. If no credible solution exists, say so."

Multi-pass generation:
- Pass 1: Generate neutral extrapolation from signals
- Pass 2: Rewrite emphasizing constructive outcomes while keeping factual grounding
- Pass 3: Generate platform-specific social captions

---

## Brand Architecture

### Domain Structure

Single domain with subdomain routing:

```
augur.news                        ← hub/landing page
├── the.augur.news                ← general predictions, English
├── der.augur.news                ← general predictions, German (DACH)
├── financial.augur.news          ← market sentiment, English
└── finanz.augur.news             ← market sentiment, German (DACH)
```

DNS: `*.augur.news` → GitHub Pages (CNAME). Path-based brand routing for MVP (`augur.news/the/`, `/der/`, etc.). Subdomain routing evaluable later via separate repos or Cloudflare proxy.

### Brand Configurations

| Brand | Subdomain | Locale | Module | Audience | Social Targets |
|-------|-----------|--------|--------|----------|----------------|
| The Augur | `the.augur.news` | en | general | General, English | X, Bluesky, FB |
| Der Augur | `der.augur.news` | de | general | General, DACH | X, Mastodon, LinkedIn DACH |
| Financial Augur | `financial.augur.news` | en | markets | Retail investors, EN | X, LinkedIn, Reddit |
| Finanz Augur | `finanz.augur.news` | de | markets | Retail investors, DACH | X, LinkedIn DACH, Mastodon |

### Visual Identity

**The Augur / Der Augur** (classic broadsheet):
- Fonts: Playfair Display (headings), Lora (body), JetBrains Mono (meta/dates)
- Background: `#f4f0e8` (aged paper)
- Ink: `#1a1a1a`
- Accent: `#8b0000` (deep red) / `#1a3a5c` (deep blue for Der Augur)
- Images: Fake photographs — photorealistic AI-generated editorial photography (FLUX.2 klein 4B, Apache 2.0; Replicate primary, fal.ai fallback)
- Layout: Single-column, justified text, drop caps, rule lines

**Financial Augur / Finanz Augur** (financial broadsheet):
- Cooler palette: `#f0f2f4` bg, `#0a6e3a` accent (green)
- Same typography
- Additional: Sentiment bar with confidence meter

### Theme as Config

```typescript
interface BrandConfig {
  name: string                    // "The Augur"
  slug: string                    // "the" (URL path prefix)
  locale: 'en' | 'de'
  module: 'general' | 'markets'
  masthead: string                // display name
  subtitle: string
  horizons: HorizonConfig[]
  palette: PaletteConfig
  imageStylePrefix: string        // prepended to every image gen prompt
  tonePrompt: string              // injected into LLM system prompt
  legalDisclaimer: string
  osintSources: SourceConfig[]    // locale-appropriate feeds
  socialTargets: SocialPlatform[]
  tradeSystemFeed?: string        // path to sentiment.json (financial brands only)
}
```

Future spin-offs (different visual themes, same pipeline) are just additional config files:
- SIGNAL (cyberpunk, tech audience)
- The Solaris (solarpunk, climate audience)
- The Iron Gazette (art deco, alt-history)

---

## URL Scheme & Horizons

### Three Horizons

All dates are full ISO `YYYY-MM-DD`. Tomorrow (literal next day) is the anchor date. All horizons project from it.

**English** (The Augur, Financial Augur):

| Key | Slug | Label | Fictive date offset | Refresh cadence |
|-----|------|-------|---------------------|-----------------|
| tomorrow | `/tomorrow/` | Tomorrow | +1 day | Every 6 hours |
| soon | `/soon/` | Soon | +1 month from tomorrow | Daily |
| future | `/future/` | Future | +1 year from tomorrow | Weekly |

**German** (Der Augur, Finanz Augur):

| Key | Slug | Label | Fictive date offset | Refresh cadence |
|-----|------|-------|---------------------|-----------------|
| tomorrow | `/morgen/` | Morgen | +1 day | Every 6 hours |
| soon | `/bald/` | Bald | +1 month from tomorrow | Daily |
| future | `/zukunft/` | Zukunft | +1 year from tomorrow | Weekly |

### URL Format

Same URL serves as both permalink and archive entry:

```
the.augur.news/tomorrow/2026-03-04
the.augur.news/soon/2026-04-04
the.augur.news/future/2027-03-04

der.augur.news/morgen/2026-03-04
der.augur.news/bald/2026-04-04
der.augur.news/zukunft/2027-03-04

financial.augur.news/tomorrow/2026-03-04
finanz.augur.news/morgen/2026-03-04
```

`/latest` redirects:

```
the.augur.news/tomorrow/latest   → 302 → /tomorrow/2026-03-04
the.augur.news/soon/latest       → 302 → /soon/2026-04-04
```

Always 302 (not 301) — social links can use `/latest` but search engines index dated URLs.

Browsing = navigating up:

```
the.augur.news/tomorrow/         → all Tomorrow predictions, reverse chrono
the.augur.news/                  → all horizons, interleaved
```

Anchor date rolls forward each cycle: On March 4th:

```
/tomorrow/2026-03-05
/soon/2026-04-05
/future/2027-03-05
```

### Horizon Config

```typescript
interface HorizonConfig {
  key: 'tomorrow' | 'soon' | 'future'
  slug: string             // locale-specific URL segment
  label: string            // display name
  refreshCron: string      // cron expression
  dateOffset: string       // "+1d" | "+1m" | "+1y"
}
```

Front matter stores the `key`. Jekyll routing maps `slug ↔ key` per brand config in `_data/brands.yml`.

---

## Article Structure

### General Predictions (The Augur / Der Augur)

```
┌─────────────────────────────────────────┐
│ ☽ THE AUGUR                             │
│ ═══════════════════════════════════════  │
│                                         │
│ ◆ TOMORROW                              │
│ Foreseen for: 2026-03-04               │
│ ─────────────────────────────────────── │
│                                         │
│ HEADLINE IN LARGE SERIF                 │
│                                         │
│ ┌─────────────────────────────────┐     │
│ │ [AI-generated photograph]       │     │
│ │ ⚠ AI-GENERATED · NOT A PHOTO   │     │
│ └─────────────────────────────────┘     │
│                                         │
│ ⚡ THE SIGNAL                           │
│ [Factual description of current         │
│  real-world signals, sourced]           │
│                                         │
│ 🔮 THE EXTRAPOLATION                    │
│ [Where this leads if unchecked]         │
│                                         │
│ 🛠️ IN THE WORKS                         │
│ [Real solutions being developed,        │
│  named, sourced]                        │
│                                         │
│ ── Sources ──                           │
│ · [1] Source title                      │
│ · [2] Source title                      │
│                                         │
│ #tag1 #tag2 #tag3                       │
│                                         │
│ Divined: 2026-03-03T14:22Z             │
│ Model: claude-sonnet-4-5                │
│ the.augur.news/tomorrow/2026-03-04      │
│                                         │
│ ░░ AI-GENERATED SPECULATION ░░░░░░░░░░ │
└─────────────────────────────────────────┘
```

### Financial Predictions (Financial Augur / Finanz Augur)

Same as above, plus a sentiment block after "In The Works":

```
│ ◈ THE AUGUR'S SENTIMENT                │
│ Semiconductors · Bullish                │
│ Horizon: Tomorrow                       │
│ Confidence: ██████░░░░ 60%             │
│                                         │
│ ⚠ AI-generated opinion, not financial   │
│ advice. The Augur holds positions in    │
│ discussed sectors.                      │
```

Sentiment comes from the trading system via `sentiment.json`:

```json
{
  "sector": "semiconductors",
  "direction": "bullish",
  "confidence": 0.6,
  "horizon": "tomorrow",
  "rationale_signals": ["tsmc-capex", "asml-backlog"],
  "generated_at": "2026-03-03T14:00:00Z"
}
```

**Firewall**: trade.sh outputs sentiment summary only. No amounts, no tickers, no order details ever enter the content pipeline. Never expose exact positions. Frame as sector-level opinion only.

### German Sections

| EN | DE |
|----|----|
| The Signal | Das Signal |
| The Extrapolation | Die Extrapolation |
| In The Works | In Arbeit |
| Sources | Quellen |
| The Augur's Sentiment | Die Einschätzung des Augur |
| Foreseen for | Vorhergesagt für |
| Divined | Erstellt |

---

## Social Distribution

### The Image Is the Distribution Unit

Every prediction produces a standalone shareable card that works without context.

Generated per prediction, at generation time:
- **1:1** — Instagram feed, Facebook
- **9:16** — Instagram Stories/Reels, TikTok
- **16:9** — X/Twitter, OpenGraph preview

### Shareable Card Format

```
┌─────────────────────────────────┐
│ ☽ THE AUGUR                     │
│ ── TOMORROW ────────────────────│
│                                 │
│ [AI-generated scene image       │
│  with semi-transparent          │
│  text overlay]                  │
│                                 │
│ "Grid failures accelerate       │
│  across three European regions" │
│                                 │
│ 🔮 Foreseen: Mar 10, 2026      │
│ 📡 Based on 3 sources           │
│ 🔗 the.augur.news/tomorrow/... │
│                                 │
│ ⚠ AI-generated speculation      │
│ ░░░░ WATERMARK PATTERN ░░░░░░░ │
└─────────────────────────────────┘
```

### Platform Strategy

| Platform | Format | Hook | CTA |
|----------|--------|------|-----|
| X/Twitter | Image card + thread | Bold prediction as tweet, sources as replies | "Full vision + sources: [link]" |
| Instagram | Carousel (image → sources → CTA) | Striking image, swipe for detail | Link in bio / story link |
| Facebook | Link post with OG image | Algorithm favors link posts with engagement | Direct link to article |
| Bluesky | Same as X format | Growing alt-audience | Direct link |
| Mastodon | Same as X format | Big in DACH, fits Der Augur | Direct link |
| LinkedIn | Professional framing | Financial brands | Direct link |

Staggering: Don't post everywhere simultaneously. Stagger 2-4h apart. LLM generates platform-native tone per caption:
- X: Punchy, provocative, emoji-light
- IG: More descriptive, emoji-heavy, hashtag block
- FB: Question-format hook, longer text
- Bluesky/Mastodon: X-style but more earnest

### Engagement Amplifiers

- **Oracle Scorecard** — Monthly: "What the Augur got right/wrong" → huge engagement
- **Polls** — "Do you think this will happen?" before revealing prediction
- **Source threads** — "Here's WHY the Oracle sees this" → builds credibility

### Platform API Requirements

| Platform | API | Cost | Notes |
|----------|-----|------|-------|
| X | v2 | Free tier | Free 1500 tweets/mo, needs media endpoint |
| Facebook | Graph API | Free | Must be a Page, not personal profile |
| Bluesky | AT Protocol | Free | Most open, easiest to automate |
| Mastodon | REST API | Free | Instance-dependent |
| LinkedIn | Marketing API | Free | Company page required |
| Instagram | Graph API | Free | Requires FB Business + Page + app review — add later |

Launch order: X + Bluesky + Mastodon → Facebook → LinkedIn → Instagram (hardest)

---

## Archive & Accountability

### Every Prediction Is Permanent

```
the.augur.news/tomorrow/               → all Tomorrow, reverse chrono
the.augur.news/tomorrow/2026-03-04     → specific prediction (permalink)
the.augur.news/tomorrow/latest         → 302 redirect to most recent
the.augur.news/                        → all horizons interleaved
the.augur.news/feed.xml                → RSS feed
the.augur.news/scorecard               → accuracy tracking page
```

### Outcome Tracking

Each prediction gets outcome tagged over time:

| Status | Meaning |
|--------|---------|
| `null` | Pending — not yet evaluable |
| `confirmed` | Prediction substantially correct |
| `partial` | Directionally correct, details off |
| `wrong` | Prediction did not materialize |

Semi-automated: LLM proposes outcome based on new OSINT, human confirms.

### Scorecard

Running accuracy stats per horizon, per topic, per brand. Public page. Being publicly wrong and owning it is the brand differentiator.

---

## Technical Architecture

### Infrastructure Reuse

Built on same base as LibreChat + OSINT MCP-based trading system:

| Asset | Existing Source | Reuse |
|-------|----------------|-------|
| Uberspace + supervisord | LibreChat | Pipeline engine (cron + scripts) |
| GitHub Pages + Jekyll | — | Static site hosting (free, CDN) |
| GitHub deploy (CI/CD) | LibreChat bootstrap | Deployment |
| ntfy | TradingAssistant | Pipeline alerts, failure notifications |
| Tavily API | Trading system MCP | News OSINT source |
| GDELT Cloud | Trading system MCP | Geopolitical OSINT |
| Yahoo Finance API | Trading system MCP | Financial data |
| Alpaca sentiment | trade.sh | Financial brand sentiment feed |
| Replicate API | Connected | Image generation (primary) |
| fal.ai API | — | Image generation (fallback) |

### System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Uberspace (assist.uber.space)                            │
│                                                             │
│  augur-engine (cron-triggered pipeline)                     │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                                                      │   │
│  │  Signal Collector                                    │   │
│  │     ├── Tavily API (news search)                     │   │
│  │     ├── GDELT Cloud API (geopolitical events)        │   │
│  │     ├── RSS feeds (curated per brand/locale)         │   │
│  │     ├── Yahoo Finance API (financial brands)         │   │
│  │     └── trade.sh sentiment.json (financial brands)   │   │
│  │              │                                       │   │
│  │  Extrapolation Pipeline (Anthropic API)              │   │
│  │     ├── Pass 1: Signals → neutral extrapolation      │   │
│  │     ├── Pass 2: Add "In The Works" + positive angle  │   │
│  │     └── Pass 3: Social captions per platform         │   │
│  │              │                                       │   │
│  │  Asset Generator                                     │   │
│  │     ├── Image gen (Replicate FLUX.2 klein 4B)        │   │
│  │     │   └── Fallback: fal.ai FLUX.2 klein 4B        │   │
│  │     ├── Watermark overlay (sharp)                    │   │
│  │     └── Social cards: 1:1, 9:16, 16:9 (sharp)       │   │
│  │              │                                       │   │
│  │  Publisher                                           │   │
│  │     ├── Write Markdown + images to augur_news branch │   │
│  │     ├── git push → GitHub Pages auto-builds Jekyll   │   │
│  │     ├── Social queue → JSON files → platform APIs    │   │
│  │     └── ntfy → pipeline status alerts                │   │
│  │                                                      │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│  Social poster (cron: */30)                                 │
│     └── Reads _data/social/pending/ → posts → moves files   │
│                                                             │
└────────────────────────┬────────────────────────────────────┘
                         │ git push (augur_news branch)
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ GitHub (ManuelKugelmann/TradingAssistant)                    │
│                                                             │
│  Branch: augur_news (GitHub Pages source)                   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Jekyll site (custom broadsheet theme)               │   │
│  │  ├── _config.yml                                     │   │
│  │  ├── _layouts/          (article, horizon, hub)      │   │
│  │  ├── _includes/         (masthead, footer, cards)    │   │
│  │  ├── _sass/             (broadsheet theme CSS)       │   │
│  │  ├── _posts/                                         │   │
│  │  │   ├── the/tomorrow/  (EN general predictions)     │   │
│  │  │   ├── der/morgen/    (DE general predictions)     │   │
│  │  │   ├── financial/     (EN financial predictions)   │   │
│  │  │   └── finanz/        (DE financial predictions)   │   │
│  │  ├── _data/                                          │   │
│  │  │   ├── brands.yml     (brand configs)              │   │
│  │  │   ├── social/        (posting queue JSON)         │   │
│  │  │   └── signals/       (cached signal data)         │   │
│  │  └── assets/                                         │   │
│  │      ├── images/        (AI-generated article images)│   │
│  │      └── cards/         (social sharing cards)       │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│  GitHub Pages auto-build on push → CDN                      │
│                                                             │
└────────────────────────┬────────────────────────────────────┘
                         │ serves
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ DNS: *.augur.news → GitHub Pages                            │
│                                                             │
│  augur.news              → hub landing page                 │
│  the.augur.news          → EN general predictions           │
│  der.augur.news          → DE general predictions           │
│  financial.augur.news    → EN financial predictions         │
│  finanz.augur.news       → DE financial predictions         │
│                                                             │
│  CNAME: augur.news in repo root                             │
│  Note: GitHub Pages supports ONE custom domain per repo.    │
│  Subdomains routed via Jekyll baseurl + collections,        │
│  or separate repos per brand if needed.                     │
└─────────────────────────────────────────────────────────────┘
```

**GitHub Pages limitation**: One custom domain per repo. Options:
1. **Single domain** — `augur.news` with path-based brands (`augur.news/the/`, `augur.news/der/`, etc.)
2. **Separate repos** — one repo per brand subdomain, each with GitHub Pages + CNAME
3. **Cloudflare proxy** — `*.augur.news` → Cloudflare → rewrite to `augur.news/{brand}/`

Recommended: **Option 1** (path-based) for MVP. Simplest. One repo, one build. Subdomain routing adds complexity for marginal benefit.

### Pipeline Flow (one cycle)

```
cron triggers: augur-cycle --brand=the --horizon=tomorrow
  │
  ├── COLLECT signals
  │    Tavily: search("top geopolitical developments today")
  │    GDELT: query(themes=["ENV_CLIMATECHANGE", "ECON_*"])
  │    RSS: fetch(brand.sources)
  │    [financial brands]: yahoo.news() + read sentiment.json
  │    Cache: write JSON → _data/signals/{source}-{timestamp}.json
  │
  ├── EXTRAPOLATE (Anthropic API)
  │    → Pass 1: system=brand.tonePrompt, user=signals+fictiveDate
  │      Output: { headline, signal, extrapolation, in_the_works, sources }
  │    → Pass 2: rewrite with positive angle (keep factual grounding)
  │    → Pass 3: generate captions for X, FB, Bluesky, etc.
  │    → Generate image prompt from article content
  │
  ├── GENERATE assets
  │    Replicate: flux-2-klein-4b (primary)
  │      └── fal.ai: flux-2-klein-4b (fallback if Replicate fails)
  │    sharp: apply watermark text overlay
  │    sharp: composite social cards (3 ratios) with headline + branding
  │
  ├── PUBLISH (git push → GitHub Pages)
  │    Write Markdown: _posts/{brand}/{horizon}/{date}-{slug}.md
  │      └── YAML front matter: all structured data (headline, sections, tags, etc.)
  │    git commit + push to augur_news branch → GitHub Pages auto-builds Jekyll
  │    Write social queue: _data/social/pending/{brand}-{date}-{platform}.json
  │
  └── NOTIFY
       ntfy: push pipeline status (success/failure/article count)
```

### Social Posting (separate process)

```
cron: */30 * * * *  augur-post

  Scan _data/social/pending/*.json
  Filter: scheduled_at <= NOW()
  Sort by scheduled_at

  For each queued post:
    → Upload image to platform
    → Post with caption + link
    → Move file: pending/ → posted/ (add post_url to JSON)
    → On failure: Move to failed/ (add error + retry_count)
```

### Cron Schedule

```bash
# ── Signal collection + generation ──

# The Augur (EN general)
0 */6 * * *   augur-cycle --brand=the --horizon=tomorrow
0 2   * * *   augur-cycle --brand=the --horizon=soon
0 3   * * 1   augur-cycle --brand=the --horizon=future

# Der Augur (DE general) — offset by 1h
0 1,7,13,19 * * *  augur-cycle --brand=der --horizon=tomorrow
0 4   * * *        augur-cycle --brand=der --horizon=soon
0 5   * * 1        augur-cycle --brand=der --horizon=future

# Financial Augur (EN markets) — offset by 2h
0 2,8,14,20 * * *  augur-cycle --brand=financial --horizon=tomorrow
30 2  * * *        augur-cycle --brand=financial --horizon=soon
0 6   * * 1        augur-cycle --brand=financial --horizon=future

# Finanz Augur (DE markets) — offset by 3h
0 3,9,15,21 * * *  augur-cycle --brand=finanz --horizon=tomorrow
30 4  * * *        augur-cycle --brand=finanz --horizon=soon
0 7   * * 1        augur-cycle --brand=finanz --horizon=future

# ── Social posting (checks queue) ──
*/30 * * * *  augur-post

# ── Housekeeping ──
0 3 * * 0     augur-scorecard    # weekly accuracy check
```

---

## Data Structure (Flat Files)

No database. All data is Markdown + JSON files on disk, git-tracked.

### Predictions = Jekyll Posts

Each prediction is a Markdown file with YAML front matter:

```
_posts/{brand}/{horizon}/{YYYY-MM-DD}-{slug}.md
```

Example: `_posts/the/tomorrow/2026-03-04-grid-failures-europe.md`

```yaml
---
brand: the
horizon: tomorrow
date_key: "2026-03-04"
fictive_date: "2026-03-04"
created_at: "2026-03-03T14:22:00Z"
headline: "Grid failures accelerate across three European regions"
tags: [energy, europe, infrastructure]
image_prompt: "Aerial view of darkened European city grid at twilight..."
image_paths: [assets/images/the-tomorrow-2026-03-04.webp]
sources:
  - title: "European Grid Status Report"
    url: "https://..."
  - title: "ENTSO-E Transparency Platform"
    url: "https://..."
# Financial brands only:
sentiment_sector: null
sentiment_direction: null
sentiment_confidence: null
# Outcome tracking:
outcome: null          # null | confirmed | partial | wrong
outcome_note: null
outcome_date: null
# LLM metadata:
model: claude-sonnet-4-5
---

## ⚡ The Signal

[Factual description of current real-world signals, sourced]

## 🔮 The Extrapolation

[Where this leads if unchecked]

## 🛠️ In The Works

[Real solutions being developed, named, sourced]
```

### Social Queue = JSON Files

```
_data/social/
├── pending/     ← awaiting posting
├── posted/      ← successfully posted (moved from pending)
└── failed/      ← failed attempts (moved from pending)
```

Each file: `{brand}-{date_key}-{platform}.json`

Example: `_data/social/pending/the-2026-03-04-x.json`

```json
{
  "brand": "the",
  "horizon": "tomorrow",
  "date_key": "2026-03-04",
  "platform": "x",
  "scheduled_at": "2026-03-03T16:00:00Z",
  "caption": "Grid failures accelerate across three European regions...",
  "image_path": "assets/cards/the-tomorrow-2026-03-04-16x9.webp",
  "created_at": "2026-03-03T14:22:00Z",
  "post_url": null,
  "retry_count": 0,
  "error": null,
  "posted_at": null
}
```

### Signal Cache = JSON Files

```
_data/signals/{source}-{YYYY-MM-DDTHH}.json
```

One file per source per fetch cycle. Pruned after 7 days. Contains raw signal data + which predictions used it.

### Outcome Tracking

Stored directly in post front matter (`outcome`, `outcome_note`, `outcome_date`). Scorecard page generated by Jekyll from front matter data across all posts.

### Why No Database

- **Zero runtime deps** — no SQLite driver, no connection management
- **Git-tracked** — every prediction versioned, diffable, restorable
- **Grep/find queryable** — standard Unix tools work on the data
- **Jekyll-native** — front matter is Jekyll's data model
- **Portable** — copy files = copy everything
- **Debuggable** — read any prediction in a text editor

---

## File Structure

Two parts: the **pipeline engine** (in this repo, runs on Uberspace) and the **Jekyll site** (on `augur_news` branch, served by GitHub Pages).

### Pipeline Engine (main branch: `augur-engine/`)

```
augur-engine/
├── package.json
├── tsconfig.json
├── .env.example                    # API key template
│
├── src/
│   ├── index.ts                    # CLI entry: augur-cycle, augur-post, augur-scorecard
│   │
│   ├── config/
│   │   ├── brands.ts               # BrandConfig[] — all 4 brands
│   │   ├── horizons.ts             # HorizonConfig per locale
│   │   └── types.ts                # Shared TypeScript types/interfaces
│   │
│   ├── collect/
│   │   ├── index.ts                # Orchestrator: collect all signals for a brand/horizon
│   │   ├── tavily.ts               # Tavily API wrapper
│   │   ├── gdelt.ts                # GDELT Cloud API wrapper
│   │   ├── rss.ts                  # RSS/Atom feed fetcher
│   │   ├── yahoo.ts                # Yahoo Finance API wrapper
│   │   └── trade-sentiment.ts      # Reads trade.sh sentiment.json output
│   │
│   ├── extrapolate/
│   │   ├── pipeline.ts             # 3-pass LLM chain orchestrator
│   │   └── prompts.ts              # System prompts per brand/horizon/locale
│   │
│   ├── assets/
│   │   ├── imagegen.ts             # Replicate primary + fal.ai fallback (FLUX.2 klein 4B)
│   │   ├── watermark.ts            # sharp: overlay watermark text
│   │   └── cards.ts                # sharp: social card compositing (3 ratios)
│   │
│   ├── publish/
│   │   ├── jekyll.ts               # Write Markdown + front matter → augur_news branch
│   │   ├── git-push.ts             # Commit + push to augur_news branch
│   │   ├── social-queue.ts         # Queue manager: write JSON files to _data/social/
│   │   └── social/
│   │       ├── x.ts                # Twitter/X API v2
│   │       ├── bluesky.ts          # AT Protocol
│   │       ├── mastodon.ts         # Mastodon REST API
│   │       ├── facebook.ts         # Meta Graph API
│   │       ├── linkedin.ts         # LinkedIn Marketing API
│   │       └── instagram.ts        # Meta Graph API (add later)
│   │
│   └── scorecard/
│       └── tracker.ts              # Outcome evaluation (semi-automated via LLM)
│
└── deploy/
    ├── setup.sh                    # Uberspace setup script
    └── crontab.txt                 # cron jobs reference
```

### Jekyll Site (`augur_news` branch)

```
/ (augur_news branch root)
├── _config.yml                     # Jekyll config (collections, defaults, plugins)
├── CNAME                           # augur.news (GitHub Pages custom domain)
├── Gemfile                         # jekyll, jekyll-feed, jekyll-seo-tag
│
├── _layouts/
│   ├── default.html                # Base layout (masthead, nav, footer)
│   ├── article.html                # Single prediction article
│   ├── horizon.html                # Horizon listing (all Tomorrow, etc.)
│   ├── brand.html                  # Brand main page (all horizons)
│   ├── hub.html                    # augur.news landing page
│   └── scorecard.html              # Accuracy tracking page
│
├── _includes/
│   ├── masthead.html               # Newspaper masthead with brand name
│   ├── article-card.html           # Article preview card (for listings)
│   ├── sentiment-bar.html          # Financial brand sentiment display
│   ├── sources.html                # Source citation block
│   ├── disclaimer.html             # AI-generated content disclaimer
│   ├── footer.html                 # Legal + impressum links
│   └── head.html                   # OpenGraph + Twitter Card meta tags
│
├── _sass/
│   ├── _base.scss                  # Reset, typography (Playfair, Lora, JetBrains)
│   ├── _broadsheet.scss            # Newspaper layout: columns, rules, drop caps
│   ├── _brands.scss                # Brand-specific palettes (aged paper, financial green)
│   ├── _article.scss               # Article page styles
│   ├── _listings.scss              # Horizon/brand listing pages
│   ├── _sentiment.scss             # Sentiment bar + confidence meter
│   └── _responsive.scss            # Mobile-first responsive
│
├── _posts/                         # Pipeline writes here (Markdown + front matter)
│   ├── the/
│   │   ├── tomorrow/
│   │   ├── soon/
│   │   └── future/
│   ├── der/
│   │   ├── morgen/
│   │   ├── bald/
│   │   └── zukunft/
│   ├── financial/
│   │   ├── tomorrow/
│   │   ├── soon/
│   │   └── future/
│   └── finanz/
│       ├── morgen/
│       ├── bald/
│       └── zukunft/
│
├── _data/
│   ├── brands.yml                  # Brand configs (name, palette, locale, etc.)
│   ├── social/                     # Social posting queue (pending/posted/failed)
│   └── signals/                    # Cached signal data (pruned after 7 days)
│
├── assets/
│   ├── css/main.scss               # Jekyll SCSS entry point
│   ├── images/                     # AI-generated article images
│   ├── cards/                      # Social sharing cards (1:1, 9:16, 16:9)
│   └── fonts/                      # Self-hosted web fonts (optional)
│
├── the/                            # EN general brand pages
│   ├── index.html                  # Brand landing
│   ├── tomorrow/index.html         # Horizon listing
│   ├── soon/index.html
│   └── future/index.html
├── der/                            # DE general brand pages
│   ├── index.html
│   ├── morgen/index.html
│   ├── bald/index.html
│   └── zukunft/index.html
├── financial/                      # EN financial brand pages
├── finanz/                         # DE financial brand pages
│
├── feed.xml                        # Jekyll RSS feed template
├── scorecard/index.html            # Accuracy tracking page
├── impressum/index.html            # Legal (German requirement)
├── datenschutz/index.html          # Privacy policy (DSGVO)
└── 404.html                        # Custom 404
```

---

## Dependencies

### Pipeline Engine (Node.js, runs on Uberspace)

- `sharp` — image compositing, watermarks, card generation
- `rss-parser` — RSS/Atom feed parsing
- Node built-in `fetch` — API calls (Anthropic, Replicate, fal.ai, social platforms)
- `simple-git` — programmatic git operations (push to augur_news branch)
- TypeScript, `tsx`

### Jekyll Site (augur_news branch)

- `jekyll` (~4.3) — static site generator
- `jekyll-feed` — RSS/Atom feed generation
- `jekyll-seo-tag` — OpenGraph + Twitter Card meta
- Custom broadsheet theme (in `_sass/`, no external theme gem)

### APIs (env vars)

- `ANTHROPIC_API_KEY` — LLM extrapolation
- `REPLICATE_API_TOKEN` — FLUX.2 klein 4B image generation (primary)
- `FAL_KEY` — FLUX.2 klein 4B image generation (fallback)
- `TAVILY_API_KEY` — news search
- `TWITTER_BEARER_TOKEN` + `TWITTER_API_KEY` + `TWITTER_API_SECRET` + `TWITTER_ACCESS_TOKEN` + `TWITTER_ACCESS_SECRET` — X posting
- `BLUESKY_HANDLE` + `BLUESKY_APP_PASSWORD` — Bluesky posting
- `MASTODON_INSTANCE` + `MASTODON_ACCESS_TOKEN` — Mastodon posting
- `FACEBOOK_PAGE_ID` + `FACEBOOK_ACCESS_TOKEN` — Facebook posting
- `LINKEDIN_ACCESS_TOKEN` — LinkedIn posting (later)
- `NTFY_URL` + `NTFY_TOKEN` — pipeline notifications

---

## Legal & Compliance

### All Brands

- Every article: generation date, model name, permalink
- Every image: "AI-GENERATED · NOT A PHOTO" watermark (visible, not removable by crop)
- Every page: persistent disclaimer bar
- RSS feed: disclaimer in channel description

### German Brands (Der Augur, Finanz Augur)

- Impressum required (TMG §5)
- DSGVO privacy policy
- Kennzeichnungspflicht: "KI-generierte Spekulation — Keine Nachricht"
- Prominently displayed, legally reviewed

### Financial Brands

- "NOT FINANCIAL ADVICE" on every article and social post
- "AI-generated opinion, not financial advice"
- "The Augur holds positions in discussed sectors"
- Sector-level only — no specific ticker recommendations
- No exact positions/amounts exposed
- Compliant with SEC (US) and BaFin (DE) guidelines for opinion content

---

## Site Requirements

The website is optimized as a landing page for social traffic, not a reading destination:

- Static HTML, CDN-served, <1s load target
- Mobile-first (90%+ of social referral traffic is mobile)
- Rich OpenGraph + Twitter Card meta tags per article
- Email capture CTA: "Get the Oracle's visions before social" (builds owned audience, add later)
- Short, memorable URLs (the URL scheme above)
- UTM tracking per platform per post
- Semantic HTML, readable without JS
- SEO: dated URLs indexed, /latest is 302 not 301

---

## Build Phases

| Phase | What | Depends on | Effort |
|-------|------|------------|--------|
| P0 | Jekyll site scaffold + custom broadsheet theme + augur_news branch | Nothing | 1 day |
| P1 | Config system + CLI skeleton + types | Nothing | 0.5 day |
| P2 | Signal collector (Tavily + RSS) | P1 | 1 day |
| P3 | Extrapolation pipeline (3-pass LLM) | P2 | 1 day |
| P4 | Markdown publisher + git push to augur_news | P0, P3 | 1 day |
| P5 | Image gen (Replicate + fal.ai fallback) + watermark + social cards | P3 | 2 days |
| P6 | Social autoposting (X + Bluesky first) | P5 | 2 days |
| P7 | Der Augur (German brand config + DE layouts) | P0-P6 | 0.5 day |
| P8 | Financial brands + trade.sh integration | P0-P6 + trading sys | 1 day |
| P9 | Scorecard / outcome tracking | P4 | 1 day |
| P10 | GDELT + Yahoo Finance collectors | P2 | 1 day |
| P11 | Mastodon + Facebook posting | P6 | 1 day |
| P12 | LinkedIn + Instagram posting | P6 | 1 day |
| P13 | Email capture + newsletter | P4 | 1 day |

**MVP** (The Augur EN, Jekyll on GitHub Pages, X + Bluesky posting): P0–P6 ≈ 8 days

---

## Costs (estimated per month)

| Item | Cost |
|------|------|
| Uberspace hosting (pipeline only) | ~€5/mo |
| GitHub Pages (Jekyll site hosting) | $0 |
| Anthropic API (Sonnet, ~120 articles/mo) | ~$5-10/mo |
| Replicate (FLUX.2 klein 4B, ~120 images/mo) | ~$1.80/mo |
| fal.ai (fallback only, ~10% of images) | ~$0.20/mo |
| Tavily (free tier 1000/mo) | $0 |
| GDELT (free) | $0 |
| Domain (augur.news) | ~$20/year |
| Social platform APIs | $0 (free tiers) |
| **Total** | **~$13-18/mo** |

---

## Prototype

A working React prototype exists: `the-augur-prototype.jsx`

Contains all 4 brands, 3 horizons each, 12 mock articles with realistic content. Features:
- Classic broadsheet newspaper styling
- Signal → Extrapolation → In The Works structure
- Sentiment bar for financial brands
- Auto-cycle mode with progress bar
- Keyboard navigation (Space, ← →)
- Brand switching, horizon tabs
- Watermark placeholders, source sections, tags, permalinks

Use as visual reference for the custom Jekyll broadsheet theme (`_sass/` + `_layouts/`).

---

## Open Questions

- **Project rename**: Consider renaming the main project/brand (The Augur → ?)
- **Multi-domain**: GitHub Pages supports one CNAME per repo. Path-based routing (`augur.news/the/`, `/der/`) for MVP, evaluate subdomain approach later.

---

## Future Ideas (post-MVP)

- "Claim This Prediction" — users bet reputation points on predictions, leaderboard
- Spin-off themes — SIGNAL (cyberpunk), The Solaris (solarpunk), The Iron Gazette (art deco) — same pipeline, different CSS + image style + tone prompt
- Outcome API — machine-readable prediction accuracy data
- Webhook integrations — push predictions to Slack, Discord, Telegram
- Multi-language — French, Spanish, Japanese brands
- Podcast — TTS narration of daily predictions
- Trading system deeper integration — auto-generate predictions from position changes
