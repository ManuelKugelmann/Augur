# Multi-Agent Architecture — TradingAssistant on LibreChat

## Goal

Layered agent pyramid: data scrapers feed storage, reasoning agents analyze and write
back, cross-cutting agents synthesize across domains, autonomous planner/trader operates
on cron, live chat assistant serves the user. Each layer can only see downward.

**Requires**: LibreChat >= 0.8.1 (Agent Handoffs).

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  L5  LIVE CHAT ASSISTANT                          (user-facing) │
│       Can hand off to ANY agent below                           │
│       Owns plans, executes trades, watches portfolio            │
├─────────────────────────────────────────────────────────────────┤
│  L4  AUTONOMOUS AGENTS                            (autonomous)   │
│       T4-shared: general data updates + shared research         │
│       T4-user:  per-user plans, plan research, trade execution  │
│       Both can use ALL agents below                             │
├─────────────────────────────────────────────────────────────────┤
│  L3  CROSS-CUTTING REASONING                     (synthesis)    │
│       Reads across ALL domain data in storage                   │
│       Writes: briefings, composite scores, predictions          │
│       Detects cross-domain patterns (disaster → supply chain)   │
├───────────────────────┬─────────────────────────────────────────┤
│  L2  DOMAIN ANALYSTS  │  Per-domain reasoning, summary,        │
│                       │  prediction. Hand off to data agents    │
│  market-analyst       │  for reads, write NOTES back.           │
│  osint-analyst        │                                         │
│  signals-analyst      │  Each analyst owns one domain.          │
├───────────────────────┼─────────────────────────────────────────┤
│  L1  DATA AGENTS      │  Thematic data collection. Scrape MCPs, │
│                       │  own profiles, snapshots, events.       │
│  market-data          │  Also read from storage on request.     │
│  osint-data           │  + filesystem                            │
│  signals-data         │                                         │
├───────────────────────┼─────────────────────────────────────────┤
│  UTILITY AGENTS       │  Stateless helpers for specific tasks.  │
│                       │  Called by L4/L5 (and others) via       │
│  trader               │  handoff. No storage ownership.         │
│  charter              │                                         │
├───────────────────────┴─────────────────────────────────────────┤
│  STORAGE              │  Profiles (JSON/git), Snapshots (Mongo), │
│                       │  Notes (Mongo), Plans (Mongo),           │
│                       │  Files                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Layer Definitions

### L1 — Data Agents (scrape → store profiles/snapshots/events → return)

Thematic agents that own **all raw data**: profiles, snapshots, and events.
They scrape MCP data sources, write to storage, AND return results to callers.
They also read from storage when asked (history, profiles, events).

Dual behavior is critical:
- On **cron**: scraper stores data, return value is ignored.
- On **interactive handoff**: scraper stores data AND returns it, so the
  calling agent doesn't need to re-read storage (avoids double search).

| Agent | MCP Data Tools | Storage Tools (read + write) | Cron Trigger |
|-------|---------------|------------------------------|-------------|
| **market-data** | `econ_indicator`, `econ_fred_series`, `econ_worldbank_indicator`, `econ_imf_data`, `commodity_trade_flows`, `commodity_energy_series`, yahoo-finance, prediction-markets | `store_snapshot`, `store_event`, `store_history`, `store_trend`, `store_get_profile`, `store_put_profile`, `store_find_profile`, `store_search_profiles`, `store_list_profiles`, `store_chart` | Hourly (prices), daily (indicators) |
| **osint-data** | `disaster_hazard_alerts`, `conflict_acled_events`, `conflict_ucdp_conflicts`, `conflict_reliefweb_reports`, `weather_*`, `health_*`, `politics_*`, `transport_*`, `agri_*`, GDELT Cloud | Same store tools as market-data | Every 6h (disasters, conflicts), daily (weather, agri) |
| **signals-data** | rss, reddit, hn, crypto-feargreed | Same store tools as market-data | Every 2h (RSS/Reddit), every 6h (HN) |

**Owns**: `store_snapshot`, `store_event`, `store_history`, `store_trend`,
`store_get_profile`, `store_put_profile`, `store_find_profile`,
`store_search_profiles`, `store_list_profiles`, `store_nearby`,
`store_recent_events`, `store_archive_snapshot`, `store_archive_history`,
`store_compact`, `store_aggregate`, `store_chart`.

**System prompt pattern** (all L1 agents):

> You are the {domain} data agent. You fetch data, manage profiles/snapshots/events,
> and return results.
>
> **Scraping** (when triggered by cron or handoff):
> 1. Call the data tools listed in your instructions.
> 2. For each result, call `store_snapshot()` or `store_event()` with structured data.
> 3. Update profiles via `store_put_profile()` when entity metadata changes.
> 4. ALSO return the fetched data so the caller can use it immediately.
> 5. If an API fails, store an event with `severity: "low"` noting the failure.
> 6. Return: {fetched: N, stored: N, errors: N, data: [{kind, entity, values...}, ...]}.
>
> **Reading** (when asked for data):
> 1. Use `store_history()`, `store_trend()`, `store_recent_events()` for time series.
> 2. Use `store_get_profile()`, `store_find_profile()` for entity info.
> 3. Use `store_chart()` for visualizations.
> 4. Return the actual data, not just confirmation.
>
> Never analyze or interpret. Store and return raw facts.

**Model**: Haiku (cheapest — no reasoning needed).

---

### L2 — Domain Analysts (read via data agents → reason → write notes)

Per-domain agents that hand off to data agents to read raw data, apply domain
expertise, and write **notes** (analysis, assessments, journal entries) back to storage.
Each analyst owns exactly one domain.

| Agent | Reads Via | Writes (notes) | Reasoning Tasks |
|-------|----------|----------------|-----------------|
| **market-analyst** | Hands off to market-data for history, trends, profiles | `store_save_note(kind=note)`, `store_get_notes`, `store_update_note`, `store_delete_note` | Price trends, indicator divergences, sector rotation, prediction market shifts |
| **osint-analyst** | Hands off to osint-data for events, country snapshots, profiles | Same note tools | Threat assessment, impact scoring, country risk updates, supply chain exposure |
| **signals-analyst** | Hands off to signals-data for signal history, events | Same note tools | Sentiment aggregation, narrative detection, filing significance, social momentum |

**Owns**: `store_save_note`, `store_get_notes`, `store_update_note`, `store_delete_note`.

**System prompt pattern** (all L2 agents):

> You are the {domain} analyst. You analyze data and produce notes.
>
> **Reading data**: Hand off to your data agent ({domain}-data) to fetch
> history, trends, profiles, and events. The data agent returns the actual data.
>
> **Writing analysis**:
> 1. Apply domain expertise: identify trends, anomalies, risk signals.
> 2. Write analysis as notes via `store_save_note(kind="note", tags=["{domain}", ...])`.
> 3. Use `store_get_notes()` to read your own previous analysis for context.
> 4. Return structured output: {domain, key_findings: [...], risk_level, confidence}.
>
> You do NOT call data MCP tools directly. You hand off to the data agent.
> You do NOT fetch live data. You only analyze what data agents have stored.

**Model**: Sonnet (needs reasoning, pattern detection, judgment).

**Handoff edges**: → {domain}-data (for reading storage).

---

### L3 — Cross-Cutting Reasoning (multi-domain → synthesize → write notes)

Reads across ALL domains by handing off to data agents and reading analyst notes.
Detects cross-domain patterns that no single analyst can see. Writes composite
notes (briefings, predictions, assessments).

| Agent | Reads Via | Writes (notes) | Cross-Domain Tasks |
|-------|----------|----------------|-------------------|
| **synthesizer** | Hands off to all 3 data agents for raw data; reads all analyst notes via `store_get_notes` | `store_save_note(kind=note, tags=["briefing"/"prediction"/"alert", ...])` | Morning briefings, cross-domain correlations (earthquake → supply chain → stock impact), composite risk scores, forward-looking predictions |

**Owns**: Same note tools as L2 (`store_save_note`, `store_get_notes`,
`store_update_note`, `store_delete_note`).

**System prompt**:

> You are the Cross-Domain Synthesizer. You read analysis notes from ALL domain
> analysts and raw data from ALL data agents, then detect patterns that span domains.
>
> **Reading**:
> - Hand off to market-data, osint-data, signals-data for raw data as needed.
> - Read analyst notes via `store_get_notes(tag="market"/"osint"/"signals")`.
>
> Examples of cross-domain signals:
> - Earthquake in Taiwan (osint) → TSMC supply risk (market) → semiconductor price impact
> - Drought in US Midwest (osint) → corn/soybean futures (market) → food price inflation
> - Reddit momentum on ticker (signals) + positive earnings (market) → high-conviction signal
> - Conflict escalation (osint) → oil price spike (market) → energy sector rotation
>
> **Writing**:
> 1. Identify cross-domain correlations and causal chains.
> 2. Score composite risk/opportunity for tracked entities.
> 3. Write briefings via `store_save_note(kind="note", tags=["briefing", ...])`.
> 4. Write predictions via `store_save_note(kind="note", tags=["prediction", ...])`.
> 5. Return: {briefing_type, key_signals: [...], predictions: [...], confidence}.

**Model**: Sonnet or Opus (highest reasoning quality needed).

**Handoff edges**: → market-data, osint-data, signals-data (for reading raw storage).

---

### L4 — Autonomous Agents (two variants: shared + per-user)

Two T4 agents run autonomously. **T4-shared** handles general data freshness
and shared research (no user context). **T4-user** handles per-user plans,
plan-relevant research, and trade execution (needs `X-User-ID`).

#### T4-shared — General Data & Research

Keeps data fresh and produces shared research available to all users.
No per-user state — uses only shared tools.

| Capability | How |
|-----------|-----|
| Refresh data | Hands off to market-data, osint-data, signals-data |
| Trigger analysis | Hands off to market-analyst, osint-analyst, signals-analyst |
| Request synthesis | Hands off to synthesizer |
| Shared research | `store_save_research`, `store_get_research`, `store_update_research` |
| Generate charts | Hands off to **charter** utility agent |

**Owns**: `store_save_research`, `store_get_research`, `store_update_research`,
`store_delete_research`.

**System prompt**:

> You are the Shared Research Agent. You run autonomously on a schedule.
> Your job: keep data fresh and produce shared research for all users.
>
> Routine:
> 1. Hand off to data agents to refresh snapshots for key entities.
> 2. Hand off to analysts for domain-specific analysis.
> 3. Hand off to synthesizer for cross-domain patterns.
> 4. Save findings as shared research via `store_save_research()`.
> 5. Update existing research when data changes.
>
> You do NOT access per-user notes, plans, or notifications.
> You do NOT execute trades.
> Priority: high-severity events > major market moves > routine coverage.

**Model**: Sonnet (needs judgment for research prioritization).

**Handoff edges**: → all L1 data agents, all L2 analysts, L3 synthesizer, charter.

#### T4-user — Per-User Planner + Executor

Runs per-user, triggered by ntfy. Owns user plans, executes plan-relevant
research, follows up on plans, executes trades via risk gate.

| Capability | How |
|-----------|-----|
| Read/write plans | `store_save_note(kind=plan)`, `store_get_notes(kind=plan)` |
| Plan-relevant research | Hands off to data agents + analysts for plan-specific queries |
| Read shared research | `store_get_research` (reads T4-shared output) |
| Execute trades | Hands off to **trader** utility agent (risk-gated) |
| Watch portfolio | Hands off to **trader** for positions, P&L, fills |
| Generate charts | Hands off to **charter** utility agent |
| Manage watchlists | Read/write `store_save_note(kind=plan, tags=["watchlist"])` |
| Check risk budget | `store_risk_status()` |
| Notify user | `store_notify(title, message)` via ntfy |

**Owns**: `store_save_note(kind=plan)`, `store_get_notes(kind=plan)`,
`store_update_note`, `store_delete_note`, `store_risk_status`, `store_notify`.

**System prompt**:

> You are the Per-User Planner. You run for a specific user on their schedule.
> Your job: execute their plans, do plan-relevant research, and notify them.
>
> Routine:
> 1. Read user's plans and watchlists (`store_get_notes(kind="plan")`).
> 2. Read shared research (`store_get_research`) for relevant context.
> 3. For plan-specific data needs, hand off to the appropriate data agent.
> 4. After gathering data, hand off to analysts for plan-relevant analysis.
> 5. If plans call for trade execution, hand off to the **trader** agent.
> 6. Check portfolio status via **trader** and log changes.
> 7. Update plans with results and next scheduled actions.
> 8. Notify the user via `store_notify()` for important events.
>
> Trading rules:
> - ALWAYS check `store_risk_status()` before handing off to trader.
> - Default to dry-run mode. Only execute live if user has enabled live trading.
> - If risk budget is low, skip lower-confidence predictions.
>
> Priority: user watchlist entities > plan deadlines > plan-relevant events.

**Model**: Sonnet (needs judgment for planning and risk decisions).

**Handoff edges**: → all L1 data agents, all L2 analysts, L3 synthesizer,
trader, charter.

---

### L5 — Live Chat Assistant (user-facing, owns plans, trades, portfolio)

The only agent the user talks to directly. Can hand off to ANY agent at any layer.
Conversational, explains reasoning, takes user input. Like L4, the chat agent
**reads and writes plans**, **executes trades** (via trader utility), and
**watches portfolio** interactively.

| Capability | How |
|-----------|-----|
| Answer questions | Hands off to appropriate data agent/analyst/synthesizer |
| Show data | Hands off to market-data (returns data directly) |
| Read/write plans | `store_save_note(kind=plan)`, `store_get_notes(kind=plan)` |
| Read analyst notes | `store_get_notes(kind=note)` |
| Execute trades | Hands off to **trader** utility agent (risk-gated) |
| Watch portfolio | Hands off to **trader** for positions, P&L, fills |
| Generate charts | Hands off to **charter** utility agent |
| Trigger cron | Hands off to L4 cron planner |
| Show briefings | Reads synthesizer notes from storage |
| Explain analysis | Reads analyst notes, adds conversational explanation |

**Owns**: Same plan tools as L4 (`store_save_note`, `store_get_notes`,
`store_update_note`, `store_delete_note` for plans). Also reads notes
(analyst output) directly.

**Handoff edges**: ALL agents (market-data, osint-data, signals-data,
market-analyst, osint-analyst, signals-analyst, synthesizer, t4-shared,
t4-user, trader, charter).

**System prompt**:

> You are the Trading Assistant. You are the user's primary interface.
> You can delegate to any specialist agent but you are the one who talks to the user.
>
> You own **plans** alongside the cron planner. The user creates plans through you;
> the cron planner executes them autonomously. You also read analyst/synthesizer
> notes directly.
>
> Available agents (hand off when needed):
>
> **Data agents** (L1 — use when user asks for data, fresh or stored):
> - market-data: stock prices, indicators, commodities, profiles, snapshots
> - osint-data: disasters, conflicts, weather, health, elections, transport
> - signals-data: RSS/SEC filings, Reddit, HN, crypto sentiment
>
> **Analysts** (L2 — use when user asks "what does this mean?"):
> - market-analyst: price trends, indicator analysis, sector rotation
> - osint-analyst: threat assessment, country risk, supply chain exposure
> - signals-analyst: sentiment analysis, narrative detection, filing significance
>
> **Synthesis** (L3 — use for cross-domain questions):
> - synthesizer: cross-domain patterns, composite risk scores, predictions
>
> **Operations** (L4):
> - cron-planner: autonomous research scheduling, plan execution on cron
>
> **Utility agents** (stateless helpers):
> - trader: execute trades, check portfolio, positions, P&L, fills
> - charter: generate charts and visualizations from store data
>
> Rules:
> 1. For data lookups, hand off to a data agent (it returns data directly).
> 2. For "what should I do?" questions, hand off to synthesizer then explain.
> 3. For trade execution, ALWAYS confirm with user before handing off to trader.
> 4. For portfolio/positions, hand off to trader (returns data directly).
> 5. For charts, hand off to charter with the data query parameters.
> 6. Keep responses conversational. Translate technical output into plain language.
> 7. Show your reasoning. Cite which agents/sources you used.

**Model**: Opus or Sonnet (needs best conversational + reasoning quality).

---

### Utility Agents — Stateless Helpers (trading + charts)

Stateless agents that perform specific operations when called via handoff.
No storage ownership — they use tools and return results. Called by L4/L5
(and potentially others).

#### Trader

Handles all broker interactions: placing orders, checking positions, portfolio
P&L, order fills, account status. All operations go through the risk gate.

| Capability | Tools |
|-----------|-------|
| Place orders | Broker tools via trading MCP (risk-gated, per-user keys) |
| Check positions | Broker portfolio/positions tools |
| View P&L | Broker account tools |
| View order fills | Broker order history tools |
| Check risk budget | `store_risk_status()` |
| Log trades | `store_event(subtype="trade", ...)` |

**System prompt**:

> You are the Trader agent. You execute trading operations through the broker API.
>
> Rules:
> 1. ALWAYS check `store_risk_status()` before any action.
> 2. NEVER exceed the daily action limit.
> 3. Default to dry-run mode. Only execute live if user has enabled live trading.
> 4. Log every action via `store_event(subtype="trade", ...)` with full rationale.
> 5. When asked for portfolio/positions/P&L, return the actual data.
> 6. Return: {action, result, risk_remaining} for trades,
>    or {positions: [...], pnl, ...} for portfolio queries.

**Model**: Haiku (stateless execution, no reasoning needed — decisions made by caller).

**MCP tools**: `trading` (broker tools + `store_risk_status` + `store_event`).

#### Charter

Generates charts and visualizations from store data. Called when any agent
needs a visual output.

| Capability | Tools |
|-----------|-------|
| Time series charts | `store_chart(kind, entity, type, fields, ...)` |
| Trend overlays | `store_trend(...)` → `store_chart(...)` |
| Comparison charts | Multiple `store_history()` → `store_chart(...)` |

**System prompt**:

> You are the Charter agent. You generate charts and visualizations.
>
> 1. Use `store_chart()` to create Plotly charts from store data.
> 2. Use `store_history()` and `store_trend()` to gather data for custom charts.
> 3. Return the chart artifact (Plotly JSON or image URL).
> 4. Accept parameters: kind, entity, type, fields, time range.

**Model**: Haiku (stateless rendering, no reasoning needed).

**MCP tools**: `trading` (`store_chart`, `store_history`, `store_trend`).

---

## Data Flow

```
                    L5 Live Chat ◄──── User
                    (PLANS + trades + portfolio)
                         │
            ┌────────────┼───────────────────┐
            ▼            ▼                   ▼
     L4 Cron Planner  L3 Synthesizer    ┌─────────┐
     (PLANS + trades) (writes NOTES)    │ UTILITY │
         │                │             │ trader  │
         │          ┌─────┼──────┐      │ charter │
         ▼          ▼     ▼      ▼      └────▲────┘
    ┌────┴────┐  L2 Mkt  OSINT  Sig       called by
    │ Schedule │  Analyst Analyst Analyst   L4/L5 via
    │ data     │  (write NOTES)            handoff
    │ + analysts│    │      │      │
    └────┬────┘     ▼      ▼      ▼
         │     handoff to data agents
         ▼          │      │      │
    ┌────┴──────────┴──────┴──────┴──┐
    │  L1 Data Agents                │
    │  market-data │ osint-data      │  own: PROFILES, SNAPSHOTS, EVENTS
    │  signals-data                  │  + filesystem
    └───────┬────────────────────────┘
            ▼
    ┌───────────────────────────────────────────────┐
    │                   STORAGE                     │
    │  Profiles │ Snapshots │ Events │ Notes │ Plans│
    │  Files                                        │
    └───────────────────────────────────────────────┘
```

**Key principle**: Each layer owns specific storage types:
- L1 data agents → profiles, snapshots, events (raw data)
- L2/L3 analysts → notes (analysis, assessments, predictions)
- L4/L5 chat/cron → plans (watchlists, trade plans, journals)
- Utility agents → no ownership (stateless: trader executes, charter renders)

Storage is the shared bus. Analysts read raw data by handing off to data agents.
L4/L5 execute trades by handing off to the trader utility agent.

---

## Agent × MCP Tool Matrix

### Storage Ownership Summary

| Layer | Owns | Storage Tools |
|-------|------|---------------|
| **L1 Data Agents** | Profiles, snapshots, events | `store_snapshot`, `store_event`, `store_history`, `store_trend`, `store_get_profile`, `store_put_profile`, `store_find_profile`, `store_search_profiles`, `store_list_profiles`, `store_nearby`, `store_recent_events`, `store_archive_*`, `store_compact`, `store_aggregate`, `store_chart` |
| **L2/L3 Analysts** | Notes (analysis, assessments) | `store_save_note`, `store_get_notes`, `store_update_note`, `store_delete_note` |
| **L4/L5 Chat+Cron** | Plans (watchlists, trade plans, journals) | `store_save_note(kind=plan)`, `store_get_notes(kind=plan)`, `store_update_note`, `store_delete_note`, `store_risk_status` |
| **Utility (trader)** | No ownership (stateless) | Broker tools, `store_risk_status`, `store_event` |
| **Utility (charter)** | No ownership (stateless) | `store_chart`, `store_history`, `store_trend` |

### L1 Data Agents — MCP Data Tools + Store Read/Write

| Agent | trading MCP tools | External MCPs |
|-------|------------------|---------------|
| **market-data** | `econ_indicator`, `econ_fred_*`, `econ_worldbank_*`, `econ_imf_data`, `commodity_*`, all store profile/snapshot/event tools | yahoo-finance, prediction-markets |
| **osint-data** | `disaster_*`, `conflict_*`, `weather_*`, `health_*`, `politics_*`, `transport_*`, `agri_*`, all store profile/snapshot/event tools | gdelt-cloud |
| **signals-data** | All store profile/snapshot/event tools | rss, reddit, hn, crypto-feargreed |

### L2 Analysts — Notes + Handoff to Data Agents

| Agent | trading MCP tools | Handoff edges |
|-------|------------------|---------------|
| **market-analyst** | `store_save_note`, `store_get_notes`, `store_update_note`, `store_delete_note` | → market-data |
| **osint-analyst** | Same note tools | → osint-data |
| **signals-analyst** | Same note tools | → signals-data |

### L3 Synthesizer — Notes + Handoff to All Data Agents

| Agent | trading MCP tools | Handoff edges |
|-------|------------------|---------------|
| **synthesizer** | Same note tools as L2 | → market-data, osint-data, signals-data |

### L4 Cron Planner — Plans + Trades + Handoff to All

| Agent | trading MCP tools | Handoff edges |
|-------|------------------|---------------|
| **cron-planner** | `store_save_note(kind=plan)`, `store_get_notes`, `store_update_note`, `store_delete_note`, `store_risk_status` | → all L1, all L2, L3, trader, charter |

### L5 Live Chat — Plans + Trades + Handoff to Everything

| Agent | trading MCP tools | Handoff edges |
|-------|------------------|---------------|
| **live-chat** | `store_save_note(kind=plan)`, `store_get_notes`, `store_update_note`, `store_delete_note`, `store_risk_status` | → ALL agents (L1, L2, L3, L4, trader, charter) |

### Utility Agents — Stateless Helpers

| Agent | trading MCP tools | Called by |
|-------|------------------|-----------|
| **trader** | Broker tools (future), `store_risk_status`, `store_event` | L4, L5 |
| **charter** | `store_chart`, `store_history`, `store_trend` | L4, L5 (and others) |

### Utility MCPs — Attached to Data Agents

The trading store is the primary storage layer (including per-user memory
via `save_memory`/`get_memories` tools). Filesystem is secondary
(for file exports/reports).

| MCP | Attached To | Purpose | Priority |
|-----|------------|---------|----------|
| filesystem | All L1 data agents | File exports, reports, documents | Secondary to trading store |

---

## MCP Server Configuration

### librechat.yaml

```yaml
mcpServers:

  # All MCPs hidden from general chat — agent-only access
  filesystem:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "__HOME__/TradeAssistant_Data/files/"]
    chatMenu: false

  trading:
    type: streamable-http
    url: http://localhost:8071/mcp
    chatMenu: false
    headers:
      X-User-ID: "{{LIBRECHAT_USER_ID}}"
      X-User-Email: "{{LIBRECHAT_USER_EMAIL}}"
      X-Broker-Key: "{{BROKER_API_KEY}}"
      X-Broker-Secret: "{{BROKER_API_SECRET}}"
      X-Broker-Name: "{{BROKER_NAME}}"
      X-Risk-Daily-Limit: "{{RISK_DAILY_LIMIT}}"
      X-Risk-Live-Trading: "{{RISK_LIVE_TRADING}}"
    customUserVars:
      BROKER_API_KEY:
        title: "Broker API Key"
        description: "Your trading broker API key"
      BROKER_API_SECRET:
        title: "Broker API Secret"
        description: "Your trading broker API secret"
      BROKER_NAME:
        title: "Broker Name"
        description: "alpaca, ibkr, binance, etc."
      RISK_DAILY_LIMIT:
        title: "Daily Action Limit"
        description: "Max trading actions per day (default: 50)"
      RISK_LIVE_TRADING:
        title: "Enable Live Trading"
        description: "Set to 'yes' for real trades. Blank = dry-run."

  # ── Tier 1 External MCPs ────────────────────

  yahoo-finance:
    command: python
    args: ["-m", "yahoo_finance_mcp"]
    chatMenu: false

  gdelt-cloud:
    type: streamable-http
    url: https://gdelt-cloud-mcp.fastmcp.app/mcp
    chatMenu: false

  prediction-markets:
    command: npx
    args: ["-y", "prediction-markets-mcp"]
    chatMenu: false

  rss:
    command: node
    args: ["__HOME__/mcps/node_modules/rss-mcp/index.js"]
    chatMenu: false

  reddit:
    command: uvx
    args: ["mcp-server-reddit"]
    chatMenu: false

endpoints:
  agents:
    recursionLimit: 25
    maxRecursionLimit: 50
    capabilities:
      - tools
      - actions
      - artifacts
      - chain
```

---

## Predefined Agents via Config (modelSpecs)

Agents are created in the Agent Builder UI (stored in MongoDB), but can be
surfaced as preset options in the UI via `modelSpecs` in `librechat.yaml`.
This makes key agents discoverable without users searching the agent list.

```yaml
modelSpecs:
  enforce: false    # false = users can still pick other agents/models
  prioritize: true  # true = these appear first in the model dropdown
  list:
    # L5 — Primary user-facing agent
    - name: "trading-assistant"
      label: "Trading Assistant"
      description: "Your AI trading assistant. Manages plans, delegates to specialist agents."
      default: true
      preset:
        endpoint: "agents"
        agent_id: "agent_LIVE_CHAT_ID"    # ← replace with actual ID from Agent Builder

    # L3 — Cross-domain synthesis
    - name: "synthesizer"
      label: "Market Synthesizer"
      description: "Cross-domain analysis: correlates disasters, markets, signals."
      preset:
        endpoint: "agents"
        agent_id: "agent_SYNTHESIZER_ID"

    # L1 — Direct data access (power users)
    - name: "market-data"
      label: "Market Data"
      description: "Direct access to market data: prices, indicators, profiles."
      preset:
        endpoint: "agents"
        agent_id: "agent_MARKET_DATA_ID"

    - name: "osint-data"
      label: "OSINT Data"
      description: "Direct access to OSINT: disasters, conflicts, weather, health."
      preset:
        endpoint: "agents"
        agent_id: "agent_OSINT_DATA_ID"
```

**Setup**: Create agents in Agent Builder UI → note their IDs → add to
`modelSpecs` in `librechat.yaml`. Agent IDs look like `agent_abc123def456`.

**Tip**: Only surface L5 (live chat) and maybe L1 data agents as modelSpecs.
L2/L3/L4 agents are used via handoff, not directly by users.

---

## Cron Schedule (L4 Research Organizer)

The research organizer runs on cron, triggering scraper → analyst → synthesizer pipelines.

| Schedule | Pipeline | Agent Chain |
|----------|----------|-------------|
| **Every 2h** | Signals refresh | signals-data → signals-analyst |
| **Every 6h** | OSINT refresh | osint-data → osint-analyst |
| **Hourly** (market hours) | Market refresh | market-data → market-analyst |
| **Daily 06:00** | Morning briefing | all data agents → all analysts → synthesizer |
| **Daily 22:00** | End-of-day summary | synthesizer (reads day's data) |
| **Weekly Sun** | Deep research | cron-planner (reviews watchlists, schedules deep dives) |

**Implementation**: LibreChat Agent Chain for deterministic pipelines.
Research organizer uses handoff edges for dynamic scheduling.

---

## Handoff Reliability Mitigation

Handoff success rate is ~60%. Strategies per layer:

| Layer | Strategy |
|-------|----------|
| L1 (data agents) | Use **Agent Chain** — deterministic, no handoff ambiguity |
| L2 (analysts) | Use **Agent Chain** after data agent completes |
| L3 (synthesizer) | Use **Agent Chain** — receives all analyst output sequentially |
| L4 (cron planner) | Use **Handoff Edges** — needs dynamic routing based on context |
| L5 (live chat) | Use **Handoff Edges** — interactive, unpredictable user queries |
| Utility (trader, charter) | Called via **Handoff Edges** from L4/L5 |

**Rule**: Use Agent Chain for deterministic pipelines (scrape → analyze → synthesize).
Use Handoff Edges only where dynamic routing is needed (L4 planner, L5 live chat).

---

## Agent Count & Cost

| Layer | Agents | Model | Calls/Day (est.) | Purpose |
|-------|--------|-------|------------------|---------|
| L1 | 3 data agents | Haiku | ~30 | Scrape + store profiles/snapshots/events |
| L2 | 3 analysts | Sonnet | ~10 | Reason + write notes |
| L3 | 1 synthesizer | Sonnet/Opus | ~3 | Cross-domain notes |
| L4 | 1 cron planner | Sonnet | ~5 | Plans + trades + portfolio |
| L5 | 1 live chat | Opus/Sonnet | ~20 (user-driven) | Plans + trades + conversation |
| Util | 2 (trader, charter) | Haiku | ~15 | Stateless trade execution + charts |
| **Total** | **11 agents** | | **~83 calls/day** | |

---

## Migration Path

### Phase 1: Data agents + utility + chat (6 agents)

- 3 data agents (market-data, osint-data, signals-data) with MCP + store access
- 2 utility agents (trader, charter)
- 1 live chat agent with handoff edges to all 5
- Validates: MCP tool filtering, handoff reliability, storage read/write, trading

### Phase 2: Add analysts (9 agents)

- 3 analysts (market-analyst, osint-analyst, signals-analyst) with note tools
- Each analyst has handoff edge to its data agent
- Wire as Agent Chains: data agent → analyst
- Chat gets handoff edges to analysts too

### Phase 3: Add synthesizer + cron (11 agents)

- L3 synthesizer with note tools + handoff edges to all data agents
- L4 cron planner with plan tools + handoff edges to all
- Wire morning briefing chain: data agents → analysts → synthesizer

---

## Comparison to Previous Flat Architecture

| Flat (previous) | Layered (this doc) | Why |
|----------------|-------------------|-----|
| 5 agents, all peer-level | 11 agents across 5 layers + utility | Separation of concerns: fetch vs. reason vs. synthesize vs. execute |
| Main agent delegates everything | L5 chat + L4 cron both orchestrate | Autonomous ops (cron) + interactive (chat) |
| Scrapers also analyze | Data agents fetch+store; analysts reason+note | Cheaper scraping (Haiku), better analysis (Sonnet) |
| No cross-domain reasoning | L3 synthesizer sees all domains | Catches disaster→supply chain→stock correlations |
| No autonomous operations | L4 cron planner runs daily pipelines | Data stays fresh without user prompting |
| Storage is incidental | Clear ownership: data→profiles/snapshots, analysts→notes, chat/cron→plans | No ambiguity about who writes what |

---

## How LibreChat Agent Delegation Works

### Handoff Edges (v0.8.1+)

Agents are configured with **edges** to other agents in the Agent Builder UI.
When Agent A has an edge to Agent B, LibreChat auto-generates a handoff tool
that transfers control. Uses LangGraph. Transitive handoffs supported (A → B → C).

**Caveat**: ~60% reliability. Mitigate with explicit system prompts and
prefer Agent Chain for deterministic pipelines.

### Agent Chain / Mixture-of-Agents (Beta)

Chains up to 10 agents sequentially. Each receives the previous agent's output.
Better for deterministic pipelines (scrape → analyze → synthesize).

### Where Agents Live

| What | Where |
|------|-------|
| MCP server definitions | `librechat.yaml` → `mcpServers` |
| Agent definitions | Agent Builder UI → stored in **MongoDB** |
| MCP → Agent binding | Agent Builder UI → per-agent tool selection |
| Tool enable/disable | Agent Builder UI → expand MCP server → toggle individual tools |
| `chatMenu: false` | Hides MCP from general chat, agent-only access |

---

## Key Design Principles

1. **Clear ownership** — data agents own profiles/snapshots/events, analysts own notes, chat/cron own plans. No ambiguity about who writes what.

2. **Data agents are dumb** — L1 agents scrape, store, and read. No reasoning = Haiku = cheap. Run them often. They also serve as the read layer for analysts.

3. **Analysts are stateless** — L2 agents hand off to data agents for reads, reason, write notes back. They don't remember previous runs. State lives in storage.

4. **Synthesizer sees everything** — L3 is the only agent that reads across all domains (via all data agents + all analyst notes). This is where cross-domain alpha lives.

5. **Two top-level orchestrators** — cron (autonomous, scheduled) and chat (interactive, user-driven). Both own plans. Neither talks to the other.

6. **Data compounds** — every data agent run adds to the time series. Every analyst run adds notes. The synthesizer gets smarter as more data accumulates. This is the moat.

7. **Return on handoff** — when a data agent is called interactively (via handoff from analyst or chat), it returns the data directly so the caller doesn't need a second read.
