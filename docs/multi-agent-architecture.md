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
│       Interactive, conversational, explains reasoning           │
├─────────────────────────────────────────────────────────────────┤
│  L4  CRON PLANNER + EXECUTOR                     (autonomous)   │
│       Research organizer: schedules what to scrape/analyze      │
│       Plan executor / trader: acts on plans via risk gate       │
│       Can use ALL agents below                                  │
├─────────────────────────────────────────────────────────────────┤
│  L3  CROSS-CUTTING REASONING                     (synthesis)    │
│       Reads across ALL domain data in storage                   │
│       Writes: briefings, composite scores, predictions          │
│       Detects cross-domain patterns (disaster → supply chain)   │
├───────────────────────┬─────────────────────────────────────────┤
│  L2  DOMAIN ANALYSTS  │  Per-domain reasoning, summary,        │
│                       │  prediction. Read domain data from      │
│  market-analyst       │  storage, write analysis back.          │
│  osint-analyst        │                                         │
│  signals-analyst      │  Each analyst owns one domain.          │
├───────────────────────┼─────────────────────────────────────────┤
│  L1  DATA SCRAPERS    │  Thematic data collection. Fetch from   │
│                       │  APIs, write raw data to storage.       │
│  market-scraper       │                                         │
│  osint-scraper        │  No reasoning — just fetch and store.   │
│  signals-scraper      │                                         │
├───────────────────────┴─────────────────────────────────────────┤
│  STORAGE              │  Profiles (JSON/git), Snapshots (Mongo), │
│                       │  Notes (Mongo), Files, Memory, SQLite    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Layer Definitions

### L1 — Data Scrapers (fetch → store)

Headless agents that collect raw data from MCP tools and write to storage.
No reasoning, no summarization. Pure ETL.

| Agent | MCP Tools | Writes To | Cron Trigger |
|-------|-----------|-----------|-------------|
| **market-scraper** | `econ_indicator`, `econ_fred_series`, `econ_worldbank_indicator`, `econ_imf_data`, `commodity_trade_flows`, `commodity_energy_series`, yahoo-finance, prediction-markets | `store_snapshot(kind=stocks/commodities/indices/crypto, ...)` | Hourly (prices), daily (indicators) |
| **osint-scraper** | `disaster_hazard_alerts`, `conflict_acled_events`, `conflict_ucdp_conflicts`, `conflict_reliefweb_reports`, `weather_forecast`, `health_disease_outbreaks`, `transport_flights_in_area`, `transport_vessels_in_area`, `agri_fao_data`, `agri_usda_crop`, GDELT Cloud | `store_snapshot(kind=countries, ...)`, `store_event(...)` | Every 6h (disasters, conflicts), daily (weather, agri) |
| **signals-scraper** | rss, reddit, hn, crypto-feargreed | `store_snapshot(kind=sources, type=signal, ...)`, `store_event(subtype=signal, ...)` | Every 2h (RSS/Reddit), every 6h (HN) |

**System prompt pattern** (all L1 agents):

> You are a data scraper. Your ONLY job is to fetch data and store it.
> 1. Call the data tools listed in your instructions.
> 2. For each result, call `store_snapshot()` or `store_event()` with structured data.
> 3. Never summarize, analyze, or interpret. Store raw facts.
> 4. If an API fails, store an event with `severity: "low"` noting the failure.
> 5. Return a count: {fetched: N, stored: N, errors: N}.

**Model**: Haiku (cheapest — no reasoning needed).

---

### L2 — Domain Analysts (read storage → reason → write back)

Per-domain agents that read raw data from storage, apply domain expertise,
and write analysis back to storage. Each analyst owns exactly one domain.

| Agent | Reads From Storage | Writes To Storage | Reasoning Tasks |
|-------|-------------------|-------------------|-----------------|
| **market-analyst** | `store_history(kind=stocks/commodities/indices/crypto)`, `store_trend(...)`, profiles | `store_snapshot(type=analysis, ...)`, `store_save_note(kind=plan)` | Price trends, indicator divergences, sector rotation, prediction market shifts |
| **osint-analyst** | `store_recent_events(...)`, `store_history(kind=countries)`, profiles | `store_event(subtype=assessment, ...)`, `store_save_note(kind=note)` | Threat assessment, impact scoring, country risk updates, supply chain exposure |
| **signals-analyst** | `store_history(kind=sources, type=signal)`, `store_recent_events(subtype=signal)` | `store_event(subtype=signal_summary, ...)`, `store_save_note(kind=note)` | Sentiment aggregation, narrative detection, filing significance, social momentum |

**System prompt pattern** (all L2 agents):

> You are the {domain} analyst. You read data from storage and produce analysis.
> 1. Use `store_history()` and `store_recent_events()` to read raw data.
> 2. Use `store_get_profile()` to understand entity context (exposures, risk factors).
> 3. Apply domain expertise: identify trends, anomalies, risk signals.
> 4. Write analysis back via `store_snapshot(type="analysis", ...)` or `store_event(subtype="assessment", ...)`.
> 5. Return structured output: {domain, key_findings: [...], risk_level, confidence}.
>
> You do NOT fetch live data. You only analyze what scrapers have already stored.

**Model**: Sonnet (needs reasoning, pattern detection, judgment).

---

### L3 — Cross-Cutting Reasoning (multi-domain → synthesize → write)

Reads across ALL domain data in storage. Detects cross-domain patterns
that no single analyst can see. Writes composite assessments.

| Agent | Reads | Writes | Cross-Domain Tasks |
|-------|-------|--------|-------------------|
| **synthesizer** | All `store_history(...)`, all `store_recent_events(...)`, all profiles, all L2 analysis snapshots | `store_event(subtype=briefing/prediction/alert)`, `store_save_note(kind=plan)` | Morning briefings, cross-domain correlations (earthquake → supply chain → stock impact), composite risk scores, forward-looking predictions |

**System prompt**:

> You are the Cross-Domain Synthesizer. You read analysis from ALL domain analysts
> and detect patterns that span domains.
>
> Examples of cross-domain signals:
> - Earthquake in Taiwan (osint) → TSMC supply risk (market) → semiconductor price impact
> - Drought in US Midwest (osint) → corn/soybean futures (market) → food price inflation
> - Reddit momentum on ticker (signals) + positive earnings (market) → high-conviction signal
> - Conflict escalation (osint) → oil price spike (market) → energy sector rotation
>
> Tasks:
> 1. Read recent analysis from market-analyst, osint-analyst, signals-analyst.
> 2. Identify cross-domain correlations and causal chains.
> 3. Score composite risk/opportunity for tracked entities.
> 4. Write briefings via `store_event(subtype="briefing", ...)`.
> 5. Write predictions via `store_event(subtype="prediction", severity=..., ...)`.
> 6. Return: {briefing_type, key_signals: [...], predictions: [...], confidence}.

**Model**: Sonnet or Opus (highest reasoning quality needed).

**MCP tools**: `trading` (store_* namespace only — history, events, profiles, notes, chart).

---

### L4 — Cron Planner + Executor (autonomous operations)

Two roles, can be one or two agents:

#### Research Organizer

Decides **what** to scrape and analyze, **when**, and **at what depth**.
Reads the plan and schedules L1/L2/L3 agents accordingly.

| Capability | How |
|-----------|-----|
| Schedule scraper runs | Hands off to market-scraper, osint-scraper, signals-scraper |
| Trigger analysis | Hands off to market-analyst, osint-analyst, signals-analyst |
| Request synthesis | Hands off to synthesizer |
| Adjust frequency | Increase scraping frequency for entities with active signals |
| Manage watchlists | Read/write `store_get_notes(kind=watchlist)` |

**System prompt**:

> You are the Research Organizer. You run autonomously on a schedule.
> Your job: ensure data is fresh, analysis is current, and nothing is missed.
>
> Routine:
> 1. Check what's in the user's watchlists (`store_get_notes(kind="watchlist")`).
> 2. For each watched entity, ensure scrapers have recent data (< 24h for prices, < 6h for events).
> 3. If data is stale, hand off to the appropriate scraper.
> 4. After scraping, hand off to the appropriate analyst.
> 5. After analysis, hand off to the synthesizer for cross-domain patterns.
> 6. Write a daily research log via `store_save_note(kind="journal")`.
>
> Priority: user watchlist entities > high-severity events > routine coverage.

#### Plan Executor / Trader

Reads plans and predictions from storage. Executes trading actions through the risk gate.

| Capability | How |
|-----------|-----|
| Read plans | `store_get_notes(kind=plan)` |
| Read predictions | `store_recent_events(subtype=prediction)` |
| Check risk budget | `store_risk_status()` |
| Execute trades | Broker tools via trading MCP (risk-gated, per-user keys) |
| Log actions | `store_save_note(kind=journal)`, `store_event(subtype=trade)` |

**System prompt**:

> You are the Plan Executor. You read trading plans and predictions from storage
> and execute them through the risk gate.
>
> Rules:
> 1. ALWAYS check `store_risk_status()` before any action.
> 2. NEVER exceed the daily action limit.
> 3. Default to dry-run mode. Only execute live if user has enabled live trading.
> 4. For each action, log via `store_event(subtype="trade", ...)` with full rationale.
> 5. If risk budget is low, skip lower-confidence predictions.
> 6. Return: {actions_taken: N, actions_skipped: N, risk_remaining: N}.

**Model**: Sonnet (needs judgment for risk decisions).

**MCP tools**: `trading` (all store_* tools + future broker tools).

---

### L5 — Live Chat Assistant (user-facing)

The only agent the user talks to directly. Can hand off to ANY agent at any layer.
Conversational, explains reasoning, takes user input.

| Capability | How |
|-----------|-----|
| Answer questions | Hands off to appropriate scraper/analyst/synthesizer |
| Show data | Hands off to market-scraper or reads storage directly |
| Modify plans | Hands off to notes or writes directly |
| Trigger research | Hands off to research organizer |
| Execute trades | Hands off to plan executor |
| Show briefings | Reads synthesizer output from storage |
| Explain analysis | Reads analyst output, adds conversational explanation |

**Handoff edges**: ALL agents (market-scraper, osint-scraper, signals-scraper,
market-analyst, osint-analyst, signals-analyst, synthesizer, research-organizer,
plan-executor, data, notes).

**System prompt**:

> You are the Trading Assistant. You are the user's primary interface.
> You can delegate to any specialist agent but you are the one who talks to the user.
>
> Available agents (hand off when needed):
>
> **Data collection** (L1 — use when user asks for fresh data):
> - market-scraper: fetch stock prices, indicators, commodities, predictions
> - osint-scraper: fetch disasters, conflicts, weather, health, elections, transport
> - signals-scraper: fetch RSS/SEC filings, Reddit, HN, crypto sentiment
>
> **Analysis** (L2 — use when user asks "what does this mean?"):
> - market-analyst: price trends, indicator analysis, sector rotation
> - osint-analyst: threat assessment, country risk, supply chain exposure
> - signals-analyst: sentiment analysis, narrative detection, filing significance
>
> **Synthesis** (L3 — use for cross-domain questions):
> - synthesizer: cross-domain patterns, composite risk scores, predictions
>
> **Operations** (L4 — use for planning and execution):
> - research-organizer: schedule research, manage watchlists
> - plan-executor: execute trading plans through risk gate
>
> **Storage** (direct access):
> - data: files, knowledge graph, SQL
> - notes: personal notes, plans, watchlists, journal
>
> Rules:
> 1. For simple data lookups, hand off to a scraper directly.
> 2. For "what should I do?" questions, hand off to synthesizer then explain.
> 3. For trade execution, ALWAYS confirm with user before handing off to executor.
> 4. Keep responses conversational. Translate technical output into plain language.
> 5. Show your reasoning. Cite which agents/sources you used.

**Model**: Opus or Sonnet (needs best conversational + reasoning quality).

---

## Data Flow

```
                    L5 Live Chat ◄──── User
                         │
            ┌────────────┼────────────────┐
            ▼            ▼                ▼
     L4 Research    L4 Plan          L3 Synthesizer
     Organizer      Executor              │
         │              │          ┌──────┼──────┐
         ▼              ▼          ▼      ▼      ▼
    ┌────┴────┐    Risk Gate    L2 Mkt  L2 OSINT  L2 Sig
    │ Schedule │                Analyst  Analyst   Analyst
    │ scrapers │                  │        │        │
    │ + analysts│                 ▼        ▼        ▼
    └────┬────┘            ┌─────┴────────┴────────┴─────┐
         │                 │         STORAGE              │
         ▼                 │  Profiles │ Snapshots │ Notes│
    ┌────┴────┐            │  Events   │ Files     │ SQL  │
    │ L1 Mkt  │            └─────▲────────▲────────▲─────┘
    │ L1 OSINT│──── write ───────┘        │        │
    │ L1 Sig  │                           │        │
    └─────────┘            L2 analysts ───┘        │
                           L3 synthesizer ─────────┘
```

**Key principle**: Data flows DOWN through scrapers into storage, then UP through
analysts and synthesizer. L4/L5 orchestrate the flow. Storage is the shared bus.

---

## Agent × MCP Tool Matrix

### L1 Scrapers — Data Tools + Store Write

| Agent | trading MCP tools | External MCPs |
|-------|------------------|---------------|
| **market-scraper** | `econ_indicator`, `econ_fred_series`, `econ_fred_search`, `econ_worldbank_indicator`, `econ_worldbank_search`, `econ_imf_data`, `commodity_trade_flows`, `commodity_energy_series`, `store_snapshot`, `store_event` | yahoo-finance, prediction-markets |
| **osint-scraper** | `disaster_hazard_alerts`, `disaster_get_earthquakes`, `disaster_get_disasters`, `disaster_get_natural_events`, `conflict_*` (all 6), `weather_*` (all 6), `health_*` (all 4), `politics_*` (all 6), `transport_*` (all 5), `agri_*` (all 4), `store_snapshot`, `store_event` | gdelt-cloud |
| **signals-scraper** | `store_snapshot`, `store_event` | rss, reddit, hn, crypto-feargreed |

### L2 Analysts — Store Read/Write Only

| Agent | trading MCP tools |
|-------|------------------|
| **market-analyst** | `store_history`, `store_trend`, `store_recent_events`, `store_get_profile`, `store_find_profile`, `store_search_profiles`, `store_chart`, `store_snapshot` (type=analysis), `store_event` (subtype=assessment), `store_save_note` |
| **osint-analyst** | Same store_* tools as market-analyst |
| **signals-analyst** | Same store_* tools as market-analyst |

### L3 Synthesizer — Store Read/Write Only

| Agent | trading MCP tools |
|-------|------------------|
| **synthesizer** | Same store_* tools as L2 analysts + `store_aggregate` |

### L4 Orchestrators — Store + Handoff Edges

| Agent | trading MCP tools | Handoff edges |
|-------|------------------|---------------|
| **research-organizer** | `store_get_notes`, `store_save_note`, `store_recent_events`, `store_history` | → all L1 scrapers, all L2 analysts, L3 synthesizer |
| **plan-executor** | `store_get_notes`, `store_save_note`, `store_recent_events`, `store_risk_status`, `store_event` (+ future broker tools) | → notes |

### L5 Live Chat — Handoff Edges to Everything

| Agent | trading MCP tools | Handoff edges |
|-------|------------------|---------------|
| **live-chat** | `store_get_notes`, `store_save_note`, `store_history`, `store_recent_events`, `store_chart`, `store_risk_status` | → ALL agents (L1, L2, L3, L4, data, notes) |

### Utility Agents — Same as Before

| Agent | MCP servers |
|-------|------------|
| **data** | filesystem, memory, sqlite |
| **notes** | trading (store_save_note, store_get_notes, store_update_note, store_delete_note, store_risk_status) |

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

  memory:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-memory"]
    env:
      MEMORY_FILE_PATH: __HOME__/TradeAssistant_Data/memory.jsonl
    chatMenu: false

  sqlite:
    command: npx
    args: ["-y", "mcp-sqlite", "__HOME__/TradeAssistant_Data/data.db"]
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

## Cron Schedule (L4 Research Organizer)

The research organizer runs on cron, triggering scraper → analyst → synthesizer pipelines.

| Schedule | Pipeline | Agent Chain |
|----------|----------|-------------|
| **Every 2h** | Signals refresh | signals-scraper → signals-analyst |
| **Every 6h** | OSINT refresh | osint-scraper → osint-analyst |
| **Hourly** (market hours) | Market refresh | market-scraper → market-analyst |
| **Daily 06:00** | Morning briefing | all scrapers → all analysts → synthesizer |
| **Daily 22:00** | End-of-day summary | synthesizer (reads day's data) |
| **Weekly Sun** | Deep research | research-organizer (reviews watchlists, schedules deep dives) |

**Implementation**: LibreChat Agent Chain for deterministic pipelines.
Research organizer uses handoff edges for dynamic scheduling.

---

## Handoff Reliability Mitigation

Handoff success rate is ~60%. Strategies per layer:

| Layer | Strategy |
|-------|----------|
| L1 (scrapers) | Use **Agent Chain** — deterministic, no handoff ambiguity |
| L2 (analysts) | Use **Agent Chain** after scraper completes |
| L3 (synthesizer) | Use **Agent Chain** — receives all analyst output sequentially |
| L4 (planner) | Use **Handoff Edges** — needs dynamic routing based on context |
| L5 (live chat) | Use **Handoff Edges** — interactive, unpredictable user queries |

**Rule**: Use Agent Chain for deterministic pipelines (scrape → analyze → synthesize).
Use Handoff Edges only where dynamic routing is needed (L4 planner, L5 live chat).

---

## Agent Count & Cost

| Layer | Agents | Model | Calls/Day (est.) | Purpose |
|-------|--------|-------|------------------|---------|
| L1 | 3 scrapers | Haiku | ~30 | Fetch + store |
| L2 | 3 analysts | Sonnet | ~10 | Reason + write |
| L3 | 1 synthesizer | Sonnet/Opus | ~3 | Cross-domain |
| L4 | 2 orchestrators | Sonnet | ~5 | Plan + execute |
| L5 | 1 live chat | Opus/Sonnet | ~20 (user-driven) | Conversation |
| Util | 2 (data, notes) | Haiku | ~10 | Storage ops |
| **Total** | **12 agents** | | **~78 calls/day** | |

---

## Migration Path

### Phase 1: Flat (current plan, no code changes)

Deploy the 5-agent flat architecture first:
- 3 scrapers (market, osint, signals) with direct MCP access
- 1 data agent, 1 notes agent
- 1 main chat agent with handoff edges to all 5

This validates MCP tool filtering, handoff reliability, and basic multi-agent flow.

### Phase 2: Add analyst layer

Split each scraper into scraper + analyst:
- Scrapers lose reasoning, gain `store_snapshot`/`store_event` write focus
- Analysts gain `store_history`/`store_trend` read focus + analysis writing
- Wire as Agent Chains: scraper → analyst

### Phase 3: Add synthesizer + cron

- Add L3 synthesizer agent
- Add L4 research organizer with cron schedule
- Wire morning briefing chain: scrapers → analysts → synthesizer

### Phase 4: Add plan executor

- Add L4 plan executor with risk gate
- Wire to broker tools (when available)
- Add L5 live chat as the new top-level agent

---

## Comparison to Previous Flat Architecture

| Flat (previous) | Layered (this doc) | Why |
|----------------|-------------------|-----|
| 5 agents, all peer-level | 12 agents across 5 layers | Separation of concerns: fetch vs. reason vs. synthesize |
| Main agent delegates everything | L5 chat + L4 cron both orchestrate | Autonomous ops (cron) + interactive (chat) |
| Scrapers also analyze | Scrapers are headless ETL; analysts reason | Cheaper scraping (Haiku), better analysis (Sonnet) |
| No cross-domain reasoning | L3 synthesizer sees all domains | Catches disaster→supply chain→stock correlations |
| No autonomous operations | L4 cron planner runs daily pipelines | Data stays fresh without user prompting |
| Storage is incidental | Storage is the shared bus between layers | All agents read/write same store → data compounds |

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

1. **Storage is the bus** — agents communicate through `store_snapshot`, `store_event`, `store_save_note`, not through direct handoff context. This decouples layers.

2. **Scrapers are dumb** — L1 agents fetch and store. No reasoning = Haiku = cheap. Run them often.

3. **Analysts are stateless** — L2 agents read from storage, reason, write back. They don't remember previous runs. State lives in storage.

4. **Synthesizer sees everything** — L3 is the only agent that reads across all domains. This is where cross-domain alpha lives.

5. **Two top-level orchestrators** — cron (autonomous, scheduled) and chat (interactive, user-driven). Both can use all agents below them. Neither talks to the other.

6. **Data compounds** — every scraper run adds to the time series. Every analyst run adds assessments. The synthesizer gets smarter as more data accumulates. This is the moat.
