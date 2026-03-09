# The Augur — Project Specification

Automated AI-powered speculative content platform. OSINT signals → LLM extrapolation → generative images → multi-brand publication → social distribution. This document is the single source of truth for Claude Code implementation.

## 1. Concept

The Augur is not news. It is a Nostradamus-style prediction engine that:

1. Collects real OSINT signals from multiple sources
2. Extrapolates plausible near-future scenarios via LLM
3. Illustrates predictions with AI-generated images
4. Publishes as an auto-refreshing, classic newspaper-style website
5. Auto-posts shareable cards to social media with link-back to source
6. Archives every prediction permanently with outcome tracking

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

Two-pass generation:
1. Generate neutral extrapolation from signals
2. Rewrite emphasizing constructive outcomes while keeping factual grounding

Third pass: Generate platform-specific social captions.

---

## 2. Brand Architecture

### 2.1 Domain Structure

Single domain with subdomain routing:

```
augur.news                        ← hub/landing page
├── the.augur.news                ← general predictions, English
├── der.augur.news                ← general predictions, German (DACH)
├── financial.augur.news          ← market sentiment, English
└── finanz.augur.news             ← market sentiment, German (DACH)
```

DNS: `*.augur.news` → single server IP (wildcard A record + wildcard TLS cert).
One Node.js process handles all brands via `req.hostname` → brand config lookup.

### 2.2 Brand Configurations

| Brand | Subdomain | Locale | Module | Audience | Social Targets |
|-------|-----------|--------|--------|----------|----------------|
| The Augur | `the.augur.news` | en | general | General, English | X, Bluesky, FB |
| Der Augur | `der.augur.news` | de | general | General, DACH | X, Mastodon, LinkedIn DACH |
| Financial Augur | `financial.augur.news` | en | markets | Retail investors, EN | X, LinkedIn, Reddit |
| Finanz Augur | `finanz.augur.news` | de | markets | Retail investors, DACH | X, LinkedIn DACH, Mastodon |

### 2.3 Visual Identity

**The Augur / Der Augur** (classic broadsheet):
- Fonts: Playfair Display (headings), Lora (body), JetBrains Mono (meta/dates)
- Background: `#f4f0e8` (aged paper)
- Ink: `#1a1a1a`
- Accent: `#8b0000` (deep red) / `#1a3a5c` (deep blue for Der Augur)
- Images: Fake photographs — photorealistic AI-generated editorial photography (FLUX.2 klein 4B, Apache 2.0)
- Layout: Single-column, justified text, drop caps, rule lines

**Financial Augur / Finanz Augur** (financial broadsheet):
- Cooler palette: `#f0f2f4` bg, `#0a6e3a` accent (green)
- Same typography
- Additional: Sentiment bar with confidence meter

### 2.4 Theme as Config

```typescript
interface BrandConfig {
  name: string                    // "The Augur"
  subdomain: string               // "the"
  locale: 'en' | 'de'
  domain: string                  // "the.augur.news"
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

## 3. URL Scheme & Horizons

### 3.1 Three Horizons

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

### 3.2 URL Format

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

### 3.3 Horizon Config

```typescript
interface HorizonConfig {
  key: 'tomorrow' | 'soon' | 'future'
  slug: string             // locale-specific URL segment
  label: string            // display name
  refreshCron: string      // cron expression
  dateOffset: string       // "+1d" | "+1m" | "+1y"
}
```

DB stores the `key`. Routing maps `slug ↔ key` per brand config.

---

## 4. Article Structure

### 4.1 General Predictions (The Augur / Der Augur)

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

### 4.2 Financial Predictions (Financial Augur / Finanz Augur)

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

### 4.3 German Sections

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

## 5. Social Distribution

### 5.1 The Image Is the Distribution Unit

Every prediction produces a standalone shareable card that works without context.

Generated per prediction, at generation time:
- **1:1** — Instagram feed, Facebook
- **9:16** — Instagram Stories/Reels, TikTok
- **16:9** — X/Twitter, OpenGraph preview

### 5.2 Shareable Card Format

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

### 5.3 Platform Strategy

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

### 5.4 Engagement Amplifiers

- **Oracle Scorecard** — Monthly: "What the Augur got right/wrong" → huge engagement
- **Polls** — "Do you think this will happen?" before revealing prediction
- **Source threads** — "Here's WHY the Oracle sees this" → builds credibility

### 5.5 Platform API Requirements

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

## 6. Archive & Accountability

### 6.1 Every Prediction Is Permanent

```
the.augur.news/tomorrow/               → all Tomorrow, reverse chrono
the.augur.news/tomorrow/2026-03-04     → specific prediction (permalink)
the.augur.news/tomorrow/latest         → 302 redirect to most recent
the.augur.news/                        → all horizons interleaved
the.augur.news/feed.xml                → RSS feed
the.augur.news/scorecard               → accuracy tracking page
```

### 6.2 Outcome Tracking

Each prediction gets outcome tagged over time:

| Status | Meaning |
|--------|---------|
| `null` | Pending — not yet evaluable |
| `confirmed` | Prediction substantially correct |
| `partial` | Directionally correct, details off |
| `wrong` | Prediction did not materialize |

Semi-automated: LLM proposes outcome based on new OSINT, human confirms.

### 6.3 Scorecard

Running accuracy stats per horizon, per topic, per brand. Public page. Being publicly wrong and owning it is the brand differentiator.

---

## 7. Technical Architecture

### 7.1 Infrastructure Reuse

Built on same base as LibreChat + OSINT MCP-based trading system:

| Asset | Existing Source | Reuse |
|-------|----------------|-------|
| Uberspace + supervisord | mkbc-mcp, LibreChat | Hosting, process management |
| Node/TS + zero-dep HTTP | mkbc-mcp | Runtime |
| GitHub deploy (CI/CD) | LibreChat bootstrap | Deployment |
| ntfy | mkbc-mcp | Pipeline alerts, failure notifications |
| Tavily API | Trading system MCP | News OSINT source |
| GDELT Cloud | Trading system MCP | Geopolitical OSINT |
| Yahoo Finance API | Trading system MCP | Financial data |
| Alpaca sentiment | trade.sh | Financial brand sentiment feed |
| MongoDB Atlas | LibreChat (optional) | — |
| Replicate API | Connected (HF MCP also available) | Image generation |

### 7.2 System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Uberspace (kugelmann.uber.space)                            │
│                                                             │
│  Existing services:                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                  │
│  │ mkbc-mcp │  │ LibreChat│  │ ntfy     │                  │
│  │ :8009    │  │ :3080    │  │ :9876    │                  │
│  └──────────┘  └──────────┘  └──────────┘                  │
│                                                             │
│  New: augur-engine                                          │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                                                      │   │
│  │  1. Signal Collector (cron-triggered)                │   │
│  │     ├── Tavily API (news search)                     │   │
│  │     ├── GDELT Cloud API (geopolitical events)        │   │
│  │     ├── RSS feeds (curated per brand/locale)         │   │
│  │     ├── Yahoo Finance API (financial brands)         │   │
│  │     └── trade.sh sentiment.json (financial brands)   │   │
│  │              │                                       │   │
│  │  2. Extrapolation Pipeline (Anthropic API)           │   │
│  │     ├── Pass 1: Signals → neutral extrapolation      │   │
│  │     ├── Pass 2: Add "In The Works" + positive angle  │   │
│  │     └── Pass 3: Social captions per platform         │   │
│  │              │                                       │   │
│  │  3. Asset Generator                                  │   │
│  │     ├── Image gen (Replicate FLUX.2 klein 4B)           │   │
│  │     ├── Watermark overlay (sharp)                    │   │
│  │     └── Social cards: 1:1, 9:16, 16:9 (sharp)       │   │
│  │              │                                       │   │
│  │  4. Publisher                                        │   │
│  │     ├── Static HTML → ~/html/augur/{brand}/          │   │
│  │     ├── Social queue → platform APIs                 │   │
│  │     └── ntfy → pipeline status alerts                │   │
│  │              │                                       │   │
│  │  5. Data Store                                       │   │
│  │     └── SQLite: predictions.db                       │   │
│  │                                                      │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│  Web backends (Uberspace reverse proxy):                    │
│    *.augur.news → static files in ~/html/augur/             │
│    the.augur.news  → ~/html/augur/the/                      │
│    der.augur.news  → ~/html/augur/der/                      │
│    financial.augur.news → ~/html/augur/financial/            │
│    finanz.augur.news → ~/html/augur/finanz/                 │
│    augur.news      → ~/html/augur/hub/                      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 7.3 Pipeline Flow (one cycle)

```
cron triggers: augur-cycle --brand=the --horizon=tomorrow
  │
  ├── 1. COLLECT signals
  │    Tavily: search("top geopolitical developments today")
  │    GDELT: query(themes=["ENV_CLIMATECHANGE", "ECON_*"])
  │    RSS: fetch(brand.sources)
  │    [financial brands]: yahoo.news() + read sentiment.json
  │
  ├── 2. EXTRAPOLATE (Anthropic API)
  │    → Pass 1: system=brand.tonePrompt, user=signals+fictiveDate
  │      Output: { headline, signal, extrapolation, in_the_works, sources }
  │    → Pass 2: rewrite with positive angle (keep factual grounding)
  │    → Pass 3: generate captions for X, FB, Bluesky, etc.
  │    → Generate image prompt from article content
  │
  ├── 3. GENERATE assets
  │    Replicate: flux-2-klein-4b with brand.imageStylePrefix + imagePrompt
  │    sharp: apply watermark text overlay
  │    sharp: composite social cards (3 ratios) with headline + branding
  │
  ├── 4. PUBLISH
  │    SQLite: INSERT prediction record
  │    Template: render article HTML → write to static file path
  │    Template: update horizon index page + main index
  │    Template: update RSS feed
  │    Queue: INSERT social posts (staggered schedule per platform)
  │
  └── 5. NOTIFY
       ntfy: push pipeline status (success/failure/article count)
```

### 7.4 Social Posting (separate process)

```
cron: */30 * * * *  augur-post

  SELECT * FROM social_queue
  WHERE scheduled_at <= NOW() AND status = 'pending'
  ORDER BY scheduled_at

  For each queued post:
    → Upload image to platform
    → Post with caption + link
    → UPDATE status = 'posted', post_url = ...
    → On failure: UPDATE status = 'failed', retry_count++
```

### 7.5 Cron Schedule

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

## 8. Database Schema

SQLite (`predictions.db`).

```sql
-- Core predictions table
CREATE TABLE predictions (
  brand      TEXT NOT NULL,       -- 'the' | 'der' | 'financial' | 'finanz'
  horizon    TEXT NOT NULL,       -- 'tomorrow' | 'soon' | 'future' (internal key, not slug)
  date_key   TEXT NOT NULL,       -- YYYY-MM-DD (full ISO, always)

  fictive_date  TEXT NOT NULL,    -- the prediction target date
  created_at    TEXT NOT NULL,    -- generation timestamp ISO
  headline      TEXT NOT NULL,
  signal        TEXT NOT NULL,    -- "The Signal" section
  extrapolation TEXT NOT NULL,    -- "The Extrapolation" section
  in_the_works  TEXT NOT NULL,    -- "In The Works" section
  sources       TEXT NOT NULL,    -- JSON array: [{title, url}]
  tags          TEXT NOT NULL,    -- JSON array: ["energy", "europe"]
  image_prompt  TEXT,
  image_paths   TEXT,             -- JSON array: paths to generated images

  -- Financial brands only
  sentiment_sector    TEXT,
  sentiment_direction TEXT,
  sentiment_confidence REAL,

  -- Outcome tracking
  outcome      TEXT,              -- NULL | 'confirmed' | 'partial' | 'wrong'
  outcome_note TEXT,
  outcome_date TEXT,

  -- LLM metadata
  model        TEXT DEFAULT 'claude-sonnet-4-5',

  PRIMARY KEY (brand, horizon, date_key)
);

-- Social posting queue
CREATE TABLE social_queue (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  brand        TEXT NOT NULL,
  horizon      TEXT NOT NULL,
  date_key     TEXT NOT NULL,
  platform     TEXT NOT NULL,     -- 'x' | 'bluesky' | 'mastodon' | 'facebook' | 'linkedin' | 'instagram'
  scheduled_at TEXT NOT NULL,     -- when to post (staggered)
  caption      TEXT NOT NULL,
  image_path   TEXT NOT NULL,     -- which ratio card to use
  status       TEXT DEFAULT 'pending',  -- 'pending' | 'posted' | 'failed'
  post_url     TEXT,              -- URL of the posted content
  retry_count  INTEGER DEFAULT 0,
  error        TEXT,
  created_at   TEXT NOT NULL,
  posted_at    TEXT,

  FOREIGN KEY (brand, horizon, date_key) REFERENCES predictions(brand, horizon, date_key)
);

-- Signal cache (avoid re-fetching within cycle)
CREATE TABLE signals (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  source     TEXT NOT NULL,       -- 'tavily' | 'gdelt' | 'rss' | 'yahoo' | 'trade'
  fetched_at TEXT NOT NULL,
  query      TEXT,
  content    TEXT NOT NULL,       -- JSON: raw signal data
  used_in    TEXT                 -- JSON array: ["the/tomorrow/2026-03-04"]
);

CREATE INDEX idx_predictions_brand_horizon ON predictions(brand, horizon);
CREATE INDEX idx_social_queue_pending ON social_queue(status, scheduled_at);
CREATE INDEX idx_signals_source_date ON signals(source, fetched_at);
```

---

## 9. File Structure

```
augur-engine/
├── CLAUDE.md                       # Claude Code instructions
├── README.md
├── package.json
├── tsconfig.json
├── .env.example                    # API key template
├── .gitignore
│
├── src/
│   ├── index.ts                    # CLI entry: augur-cycle, augur-post, augur-scorecard
│   ├── db.ts                       # SQLite setup (better-sqlite3)
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
│   │   ├── imagegen.ts             # Replicate API (FLUX.2 klein 4B)
│   │   ├── watermark.ts            # sharp: overlay watermark text
│   │   └── cards.ts                # sharp: social card compositing (3 ratios)
│   │
│   ├── publish/
│   │   ├── static.ts               # HTML template → static file writer
│   │   ├── rss.ts                  # RSS/Atom feed generator
│   │   ├── social-queue.ts         # Queue manager: schedule posts per platform
│   │   └── social/
│   │       ├── x.ts                # Twitter/X API v2
│   │       ├── bluesky.ts          # AT Protocol
│   │       ├── mastodon.ts         # Mastodon REST API
│   │       ├── facebook.ts         # Meta Graph API
│   │       ├── linkedin.ts         # LinkedIn Marketing API
│   │       └── instagram.ts        # Meta Graph API (add later)
│   │
│   └── scorecard/
│       ├── tracker.ts              # Outcome evaluation (semi-automated via LLM)
│       └── render.ts               # Scorecard page generator
│
├── templates/
│   ├── article.html                # Article page template (Mustache/Handlebars)
│   ├── horizon-index.html          # Horizon listing page template
│   ├── brand-index.html            # Brand main page template
│   ├── hub.html                    # augur.news landing page
│   ├── scorecard.html              # Accuracy tracking page
│   ├── feed.xml                    # RSS template
│   └── cards/
│       ├── card-1x1.svg            # Social card template (Instagram/FB)
│       ├── card-9x16.svg           # Social card template (Stories/Reels)
│       └── card-16x9.svg           # Social card template (X/OG)
│
├── data/
│   ├── predictions.db              # SQLite database
│   └── assets/                     # Generated images and cards
│       ├── images/                  # AI-generated article images
│       └── cards/                   # Social sharing cards
│
└── deploy/
    ├── uberspace/
    │   ├── setup.sh                # Uberspace setup script
    │   ├── augur-post.ini          # supervisord config for social poster
    │   └── crontab.txt             # cron jobs reference
    └── .env.example                # Production env template
```

---

## 10. Dependencies

### Runtime

- `better-sqlite3` — SQLite driver
- `sharp` — image compositing, watermarks, card generation
- `mustache` or `handlebars` — HTML templating
- Node built-in `fetch` — API calls (Anthropic, Replicate, social platforms)
- `rss-parser` — RSS/Atom feed parsing
- `fast-xml-parser` — GDELT XML parsing (if needed)

### APIs (env vars)

- `ANTHROPIC_API_KEY` — LLM extrapolation
- `REPLICATE_API_TOKEN` — FLUX.2 klein 4B image generation
- `TAVILY_API_KEY` — news search
- `TWITTER_BEARER_TOKEN` + `TWITTER_API_KEY` + `TWITTER_API_SECRET` + `TWITTER_ACCESS_TOKEN` + `TWITTER_ACCESS_SECRET` — X posting
- `BLUESKY_HANDLE` + `BLUESKY_APP_PASSWORD` — Bluesky posting
- `MASTODON_INSTANCE` + `MASTODON_ACCESS_TOKEN` — Mastodon posting
- `FACEBOOK_PAGE_ID` + `FACEBOOK_ACCESS_TOKEN` — Facebook posting
- `LINKEDIN_ACCESS_TOKEN` — LinkedIn posting (later)
- `NTFY_URL` + `NTFY_TOKEN` — pipeline notifications

### Dev

- TypeScript, `tsx` (or `ts-node`)
- ESLint

---

## 11. Legal & Compliance

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

## 12. Site Requirements

The website is optimized as a landing page for social traffic, not a reading destination:

- ⚡ Static HTML, CDN-served, <1s load target
- 📱 Mobile-first (90%+ of social referral traffic is mobile)
- 🏷️ Rich OpenGraph + Twitter Card meta tags per article
- 📧 Email capture CTA: "Get the Oracle's visions before social" (builds owned audience, add later)
- 🔗 Short, memorable URLs (the URL scheme above)
- 📊 UTM tracking per platform per post
- ♿ Semantic HTML, readable without JS
- 🔍 SEO: dated URLs indexed, /latest is 302 not 301

---

## 13. Build Phases

| Phase | What | Depends on | Effort |
|-------|------|------------|--------|
| P0 | DB schema + config system + CLI skeleton + types | Nothing | 1 day |
| P1 | Signal collector (Tavily + RSS) | P0 | 1 day |
| P2 | Extrapolation pipeline (3-pass LLM) | P1 | 1 day |
| P3 | Static site generator + article HTML template | P2 | 1 day |
| P4 | Image gen (Replicate) + watermark + social cards | P2 | 2 days |
| P5 | Social autoposting (X + Bluesky first) | P4 | 2 days |
| P6 | Der Augur (German brand config) | P0-P5 | 0.5 day |
| P7 | Financial brands + trade.sh integration | P0-P5 + trading sys | 1 day |
| P8 | Scorecard / outcome tracking | P3 | 1 day |
| P9 | GDELT + Yahoo Finance collectors | P1 | 1 day |
| P10 | Mastodon + Facebook posting | P5 | 1 day |
| P11 | LinkedIn + Instagram posting | P5 | 1 day |
| P12 | Email capture + newsletter | P3 | 1 day |

**MVP** (The Augur EN, static site, X + Bluesky posting): P0–P5 ≈ 8 days

---

## 14. Costs (estimated per month)

| Item | Cost |
|------|------|
| Uberspace hosting | ~€5/mo |
| Anthropic API (Sonnet, ~120 articles/mo) | ~$5-10/mo |
| Replicate (FLUX.2 klein 4B, ~120 images/mo) | ~$1.80/mo |
| Tavily (free tier 1000/mo) | $0 |
| GDELT (free) | $0 |
| Domain (augur.news) | ~$20/year |
| Social platform APIs | $0 (free tiers) |
| **Total** | **~$17-22/mo** |

---

## 15. Prototype

A working React prototype exists: `the-augur-prototype.jsx`

Contains all 4 brands, 3 horizons each, 12 mock articles with realistic content. Features:
- Classic broadsheet newspaper styling
- Signal → Extrapolation → In The Works structure
- Sentiment bar for financial brands
- Auto-cycle mode with progress bar
- Keyboard navigation (Space, ← →)
- Brand switching, horizon tabs
- Watermark placeholders, source sections, tags, permalinks

Use as visual reference for the static HTML templates.

---

## 16. Future Ideas (post-MVP)

- "Claim This Prediction" — users bet reputation points on predictions, leaderboard
- Spin-off themes — SIGNAL (cyberpunk), The Solaris (solarpunk), The Iron Gazette (art deco) — same pipeline, different CSS + image style + tone prompt
- Outcome API — machine-readable prediction accuracy data
- Webhook integrations — push predictions to Slack, Discord, Telegram
- Multi-language — French, Spanish, Japanese brands
- Podcast — TTS narration of daily predictions
- Trading system deeper integration — auto-generate predictions from position changes
