#!/usr/bin/env python3
"""Bootstrap profile data via LibreChat Agents API.

Sends structured prompts to the bootstrap agent (which delegates to L1
data agents) to populate and enrich profile data at scale.

The script is additive: existing profiles are enriched with fresh data from
MCP tools and web search; new profiles are created for missing entities.
Bootstrap targets are defined in bootstrap-targets.json.

API key and agent ID are auto-discovered from .env and the LibreChat API:
  - AUGUR_AGENTS_API_KEY from ~/augur/.env (same key used by cron)
  - Agent ID discovered via /api/agents/v1/models (matches by name)

Usage:
    # Dry run — preview prompts without calling API
    python bootstrap-data.py --dry-run

    # Bootstrap all kinds (auto-discovers API key + agent ID)
    python bootstrap-data.py

    # Bootstrap one kind with custom batch size
    python bootstrap-data.py --kind countries --batch-size 5

    # Override auto-discovery
    python bootstrap-data.py --api-key KEY --agent-id agent_ABC123
"""

import argparse
import json
import os
import sys
import random
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from agent_client import AgentClient, load_env  # noqa: E402

TARGETS_FILE = os.path.join(SCRIPT_DIR, "bootstrap-targets.json")
REPO_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
PROFILES_DIR = os.path.join(REPO_ROOT, "profiles")

DEFAULT_BASE_URL = "http://localhost:3080"
DEFAULT_BATCH_SIZE = 10
DEFAULT_AGENT_NAME = "bootstrap"
API_TIMEOUT = 300  # 5 min per batch (agent may call many tools)

VALID_KINDS = {
    "countries", "stocks", "etfs", "crypto", "indices", "sources",
    "commodities", "crops", "materials", "products", "companies",
    "regions",
}

# Minimal required fields per kind (id + name for all)
REQUIRED_FIELDS = {k: ["id", "name"] for k in VALID_KINDS}

# Kind-specific data enrichment instructions
KIND_INSTRUCTIONS = {
    "countries": (
        "For each country, use available MCP tools to fetch real data:\n"
        "- Use econ_world_bank_indicator or econ_imf_weo for GDP, population, trade data\n"
        "- Use econ_fred_series for US-specific economic indicators\n"
        "- Use macro data tools for currency, ratings, trade partners\n"
        "Populate: trade (top_exports, top_partners, major_ports), exposure "
        "(commodities_import, energy_mix, risk_factors), ratings, tags."
    ),
    "stocks": (
        "For each stock, use available MCP tools to fetch real data:\n"
        "- Use ta_analyze_full or ta_analyze_trend for current price data\n"
        "- Use finance tools for fundamentals\n"
        "Populate: exchange, sector, industry, country, fundamentals "
        "(founded, employees, market_cap), exposure (countries, commodities, "
        "supply_chain, risk_factors), tags."
    ),
    "etfs": (
        "For each ETF, use available MCP tools and your knowledge:\n"
        "- Use finance tools for current data\n"
        "Populate: exchange, issuer, strategy, exposure (countries with weights, "
        "sectors, commodities, risk_factors), tags."
    ),
    "crypto": (
        "For each cryptocurrency, populate from your knowledge and MCP tools:\n"
        "Populate: network, consensus mechanism, max_supply, exposure "
        "(countries, risk_factors), tags."
    ),
    "indices": (
        "For each index, populate from your knowledge and MCP tools:\n"
        "Populate: country, exchange, number of components, methodology, "
        "exposure (sectors, countries, risk_factors), tags."
    ),
    "commodities": (
        "For each commodity, use MCP tools where available:\n"
        "- Use commodities_eia_series for energy data\n"
        "- Use agri_faostat for agricultural commodities\n"
        "Populate: unit, benchmark, top producers, consumers, chokepoints, "
        "seasonality, exposure (countries, risk_factors), tags."
    ),
    "crops": (
        "For each crop, use MCP tools where available:\n"
        "- Use agri_faostat_data for production/trade data\n"
        "- Use agri_usda_nass for US production data\n"
        "Populate: growing_season, top producers, exporters, water_intensity, "
        "climate_sensitivity, exposure, tags."
    ),
    "materials": (
        "For each material, populate from your knowledge:\n"
        "Populate: top producers, known reserves, processing countries, "
        "end_uses, substitutes, exposure (countries, risk_factors), tags."
    ),
    "sources": (
        "For each data source, populate based on the MCP server configuration:\n"
        "Populate: mcp (server namespace like 'weather', 'econ', 'agri'), "
        "tool (primary tool name), api_base URL, auth (none/api_key/oauth), "
        "refresh (frequency, snapshot_type), signal (thresholds), ttl_days."
    ),
    "products": (
        "For each product category, populate from your knowledge:\n"
        "Populate: hs_codes (if known), key manufacturers, material inputs, "
        "trade_volume estimate, exposure (countries, materials, risk_factors), tags."
    ),
    "companies": (
        "For each company, populate from your knowledge and MCP tools:\n"
        "Populate: country, sector, industry, revenue estimate, employees, "
        "publicly_traded, ticker (if public), exposure (countries, products, "
        "materials, risk_factors), tags."
    ),
    "regions": (
        "For each region, populate from your knowledge and MCP tools:\n"
        "- type: one of continent, subregion, economic_zone, climate_zone, maritime, corridor\n"
        "- Use econ_world_bank_indicator for regional economic data\n"
        "Populate: countries (ISO3 array), bbox [west, south, east, north], "
        "climate, hazards, chokepoints (shipping/trade), "
        "exposure (commodities, risk_factors), tags."
    ),
}

# Kind-specific timeseries bootstrap instructions (rough historical data)
TIMESERIES_INSTRUCTIONS = {
    "countries": (
        "For each country, fetch rough historical economic data and store as snapshots:\n"
        "- Use econ_world_bank_indicator for GDP, GDP growth, inflation, unemployment (annual, last 5 years)\n"
        "- Use econ_fred_series for US-specific time series\n"
        "- Use econ_imf_weo for forecasts\n"
        "For each data point, call `store_snapshot(kind='countries', entity='{id}', "
        "type='macro', data={{year, gdp, gdp_growth, inflation, unemployment, ...}}, "
        "region='{region}')`. One snapshot per year."
    ),
    "stocks": (
        "For each stock, fetch recent price history and store as snapshots:\n"
        "- Use ta_analyze_full to get current OHLCV + technical indicators\n"
        "- Store the result via `store_snapshot(kind='stocks', entity='{id}', "
        "type='indicators', data={{...analysis result...}}, region='{region}')`.\n"
        "One snapshot with the current analysis is sufficient."
    ),
    "etfs": (
        "For each ETF, fetch current data and store as snapshot:\n"
        "- Use ta_analyze_full to get current OHLCV + technical indicators\n"
        "- Store via `store_snapshot(kind='etfs', entity='{id}', "
        "type='indicators', data={{...}}, region='{region}')`."
    ),
    "commodities": (
        "For each commodity, fetch recent price/production data:\n"
        "- Use commodities_eia_series for energy commodities (crude oil, natural gas)\n"
        "- Use agri_faostat_data for agricultural commodities\n"
        "- Store each data point via `store_snapshot(kind='commodities', entity='{id}', "
        "type='price', data={{...}}, region='global')`."
    ),
    "crops": (
        "For each crop, fetch recent production data:\n"
        "- Use agri_faostat_data for global production/trade\n"
        "- Use agri_usda_nass for US production\n"
        "- Store via `store_snapshot(kind='crops', entity='{id}', "
        "type='production', data={{year, production_mt, area_ha, yield_kg_ha, ...}}, "
        "region='global')`. One snapshot per available year."
    ),
}


def load_targets(targets_file: str) -> dict:
    """Load bootstrap targets from JSON file."""
    with open(targets_file) as f:
        data = json.load(f)
    # Strip metadata keys
    return {k: v for k, v in data.items() if not k.startswith("_")}


def find_existing_profiles(profiles_dir: str, kind: str) -> set[str]:
    """Find profile IDs that already exist on disk."""
    existing = set()
    profiles_path = os.path.join(profiles_dir, "")
    for region_dir in os.listdir(profiles_dir):
        region_path = os.path.join(profiles_dir, region_dir)
        if not os.path.isdir(region_path) or region_dir.startswith((".", "_")):
            continue
        if region_dir in ("SCHEMAS",):
            continue
        kind_path = os.path.join(region_path, kind)
        if not os.path.isdir(kind_path):
            continue
        for f in os.listdir(kind_path):
            if f.endswith(".json") and not f.startswith("_"):
                existing.add(f[:-5])  # strip .json
    return existing


def build_prompt(kind: str, targets: list[dict], existing_ids: set[str]) -> str:
    """Build the bootstrap prompt for a batch of targets."""
    required = REQUIRED_FIELDS.get(kind, [])
    instructions = KIND_INSTRUCTIONS.get(kind, "Populate all schema fields accurately.")

    # Classify targets as new or existing (for enrichment)
    new_targets = [t for t in targets if t["id"] not in existing_ids]
    enrich_targets = [t for t in targets if t["id"] in existing_ids]

    prompt_parts = [
        f"## Profile Bootstrap Task: {kind}\n",
        "You are bootstrapping profile data for the trading signals platform. "
        "Use MCP tools (data APIs) and web search to gather accurate, current data. "
        "For each entity, call `store_put_profile()` to create or update the profile.\n",
        f"**Schema required fields**: {', '.join(required)}",
        f"**Kind**: {kind}\n",
        f"### Data gathering instructions\n{instructions}\n",
    ]

    if enrich_targets:
        prompt_parts.append(
            "### Profiles to ENRICH (already exist — update with fresh data)\n"
            "These profiles exist but may have incomplete or stale data. "
            "First read each with `store_get_profile()`, then update with fresh data "
            "from MCP tools. Merge new data, don't overwrite existing good data.\n"
        )
        for t in enrich_targets:
            prompt_parts.append(f"- **{t['id']}** (region: {t['region']})")

    if new_targets:
        prompt_parts.append(
            "\n### Profiles to CREATE (new)\n"
            "These profiles don't exist yet. Create them with comprehensive data.\n"
        )
        for t in new_targets:
            prompt_parts.append(f"- **{t['id']}** (region: {t['region']})")

    prompt_parts.extend([
        "\n### Rules",
        "1. Call `store_put_profile(kind=\"{kind}\", id=\"{id}\", data={{...}}, region=\"{region}\")` for each entity.".format(
            kind=kind, id="{id}", region="{region}"
        ),
        "2. Set `_sources` to list the actual data sources used (e.g., [\"world_bank\", \"fred\"]).",
        "3. Do NOT set `_placeholder: true` — this is real data.",
        "4. Include `tags` array with relevant categorization tags.",
        "5. Process ALL entities listed above. Report results when done.",
        "6. If an MCP tool fails, skip that data point and note it — don't stop.",
    ])

    return "\n".join(prompt_parts)


def build_timeseries_prompt(kind: str, targets: list[dict]) -> str | None:
    """Build a timeseries bootstrap prompt for a batch of targets.

    Returns None if this kind has no timeseries instructions.
    """
    instructions = TIMESERIES_INSTRUCTIONS.get(kind)
    if not instructions:
        return None

    prompt_parts = [
        f"## Historical Timeseries Bootstrap: {kind}\n",
        "You are bootstrapping rough historical timeseries data for the trading signals "
        "platform. Use MCP tools (data APIs) to fetch real historical data points and "
        "store each as a snapshot via `store_snapshot()`.\n",
        f"### Data gathering instructions\n{instructions}\n",
        "### Entities to process\n",
    ]

    for t in targets:
        filled = instructions.replace("{id}", t["id"]).replace("{region}", t["region"])
        prompt_parts.append(f"- **{t['id']}** (region: {t['region']})")

    prompt_parts.extend([
        "\n### Rules",
        "1. Use MCP data tools to fetch REAL data — do not fabricate numbers.",
        "2. Store each data point via `store_snapshot()` with appropriate type.",
        "3. If a tool fails or returns no data for an entity, skip it and continue.",
        "4. Rough/approximate data is fine — this is seed data, not precision data.",
        "5. Process ALL entities listed above. Report results when done.",
    ])

    return "\n".join(prompt_parts)


def build_events_prompt(kind: str, targets: list[dict]) -> str:
    """Build a prompt to seed current events for a batch of entities."""
    events_instructions = {
        "countries": (
            "Delegate to osint-data to scrape GDELT, disaster feeds, and conflict trackers. "
            "Look for: active conflicts, sanctions, elections, policy changes, natural disasters, "
            "economic crises. Also delegate to signals-data for trending news about these countries."
        ),
        "stocks": (
            "Delegate to market-data for recent earnings surprises, significant price moves (>3% daily), "
            "IPOs, delistings, and rating changes. Delegate to signals-data for trending Reddit/HN "
            "discussions and breaking news about these stocks."
        ),
        "commodities": (
            "Delegate to market-data for recent price spikes/drops, supply disruptions, "
            "OPEC decisions. Delegate to osint-data for geopolitical events affecting supply chains."
        ),
        "crypto": (
            "Delegate to market-data for recent price moves. Delegate to signals-data "
            "for Reddit/HN sentiment and regulatory news."
        ),
        "regions": (
            "Delegate to osint-data for regional events: weather extremes, shipping disruptions "
            "(Suez, Panama), trade bloc policy changes, humanitarian crises."
        ),
    }
    instructions = events_instructions.get(kind,
        f"Delegate to appropriate L1 agents to find current events affecting these {kind}.")

    entity_list = "\n".join(f"- **{t['id']}** (region: {t['region']})" for t in targets)

    return (
        f"## Events Bootstrap: {kind}\n\n"
        "Seed the events collection with current real-world events for the entities below. "
        "Delegate to L1 data agents to scrape real data, then store each significant event "
        "via `event(subtype, summary, data, severity, countries, entities, region, source)`.\n\n"
        f"### Instructions\n{instructions}\n\n"
        f"### Entities\n{entity_list}\n\n"
        "### Rules\n"
        "1. Only store REAL current events — do not fabricate.\n"
        "2. Severity: routine=low, notable=medium, major disruption=high, crisis=critical.\n"
        "3. Link events to entities via `countries` (ISO3) and `entities` (IDs) arrays.\n"
        "4. Set `source` to data origin (gdelt, reddit, rss, finance, google_news).\n"
        "5. Valid subtypes: earthquake, volcano, flood, drought, wildfire, conflict, sanctions, "
        "election, policy, tariff, earnings, ipo, default, signal_change, price_spike, "
        "supply_disruption, transport, epidemic, sentiment_shift.\n"
        "6. Skip entities with no current events — don't force-create events.\n"
        "7. Report: {events_stored: N, by_severity: {...}, errors: N}."
    )


def build_plans_prompt(targets: dict) -> str:
    """Build a prompt to create initial plans and watchlists for cron-planner."""
    # Summarize what kinds and how many entities exist
    kind_summary = ", ".join(f"{k}: {len(v)}" for k, v in sorted(targets.items()))

    return (
        "## Bootstrap Plans & Watchlists\n\n"
        "Create initial research plans and watchlists so cron-planner has work from day one. "
        "First, read any existing plans (`get_notes(kind=\"plan\")`) and watchlists "
        "(`get_notes(kind=\"watchlist\")`) to avoid duplicates.\n\n"
        f"**Bootstrapped entity counts**: {kind_summary}\n\n"
        "### Plans to create (`save_note` with `kind=\"plan\"`):\n\n"
        "1. **Daily Data Refresh Plan** — title: \"Daily data refresh\"\n"
        "   Content: schedule for each entity kind, which L1 agent handles it, priority order. "
        "   Markets/stocks: 2x daily (pre-market, post-close). Commodities/crypto: daily. "
        "   Countries/regions: weekly. Sources: monthly.\n\n"
        "2. **High-Priority Watchlist Plan** — title: \"High-priority entities\"\n"
        "   Content: entities that need closer monitoring. Use `recent_events()` to find entities "
        "   with severity >= medium. Include reason for watch and suggested check frequency.\n\n"
        "3. **Coverage Gap Plan** — title: \"Coverage gaps\"\n"
        "   Content: read bootstrap journal logs (`get_notes(kind=\"journal\", tag=\"bootstrap\")`) "
        "   and identify kinds/regions with thin data. List what needs deeper enrichment.\n\n"
        "4. **Analysis Schedule** — title: \"Analysis cadence\"\n"
        "   Content: when to run L2 analysts and L3 synthesizer. After daily data refresh, "
        "   on event triggers (severity >= high), weekly deep-dive (Sundays).\n\n"
        "### Watchlists to create (`save_note` with `kind=\"watchlist\"`):\n\n"
        "1. **Market Movers** — title: \"Market movers\"\n"
        "   Content: stocks/ETFs/crypto with highest recent volatility or signal changes. "
        "   Check `recent_events(subtype=\"signal_change\")` and `recent_events(subtype=\"price_spike\")`.\n\n"
        "2. **Geopolitical Hotspots** — title: \"Geopolitical hotspots\"\n"
        "   Content: countries/regions with active conflicts, sanctions, elections, disasters. "
        "   Check `recent_events(subtype=\"conflict\")`, etc.\n\n"
        "3. **Supply Chain Risks** — title: \"Supply chain risks\"\n"
        "   Content: commodities/materials/products with disruption signals. "
        "   Check `recent_events(subtype=\"supply_disruption\")`.\n\n"
        "### Rules\n"
        "- Tag all plans with `[\"bootstrap\", \"initial\"]`.\n"
        "- Tag all watchlists with `[\"bootstrap\", \"watchlist\"]`.\n"
        "- Use markdown formatting in content for readability.\n"
        "- Include specific entity IDs in watchlists (not just categories).\n"
        "- If no events exist yet (events phase hasn't run), base watchlists on profile data "
        "  (e.g., countries with high risk_factors, volatile sectors).\n"
        "- Report: {plans_created: N, watchlists_created: N}."
    )


def batch_targets(targets: list[dict], batch_size: int) -> list[list[dict]]:
    """Split targets into batches."""
    return [targets[i:i + batch_size] for i in range(0, len(targets), batch_size)]


def run_bootstrap(
    client: AgentClient,
    agent_id: str,
    targets: dict,
    profiles_dir: str,
    kind_filter: str | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    dry_run: bool = False,
    timeseries: bool = False,
    events: bool = False,
    plans: bool = False,
) -> dict:
    """Run the full bootstrap process. Returns summary stats."""
    stats = {"kinds": 0, "batches": 0, "targets": 0, "ok": 0, "errors": 0}

    kinds_to_process = [kind_filter] if kind_filter else sorted(targets.keys())

    for kind in kinds_to_process:
        if kind not in targets:
            print(f"  SKIP: no targets for kind '{kind}'", file=sys.stderr)
            continue
        if kind not in VALID_KINDS:
            print(f"  SKIP: invalid kind '{kind}'", file=sys.stderr)
            continue

        kind_targets = targets[kind]
        existing = find_existing_profiles(profiles_dir, kind)
        batches = batch_targets(kind_targets, batch_size)

        print(f"\n{'='*60}")
        print(f"Kind: {kind} — {len(kind_targets)} targets, {len(existing)} existing, {len(batches)} batches")
        print(f"{'='*60}")
        stats["kinds"] += 1

        for i, batch in enumerate(batches, 1):
            prompt = build_prompt(kind, batch, existing)
            batch_ids = [t["id"] for t in batch]
            new_count = sum(1 for t in batch if t["id"] not in existing)
            enrich_count = len(batch) - new_count

            print(f"\n  Batch {i}/{len(batches)}: {batch_ids}")
            print(f"    New: {new_count}, Enrich: {enrich_count}")
            stats["batches"] += 1
            stats["targets"] += len(batch)

            if dry_run:
                print(f"    [DRY RUN] Prompt ({len(prompt)} chars):")
                # Print first 500 chars of prompt
                for line in prompt[:500].split("\n"):
                    print(f"      {line}")
                if len(prompt) > 500:
                    print(f"      ... ({len(prompt) - 500} more chars)")
                stats["ok"] += 1
                continue

            result = client.invoke(agent_id, prompt, timeout=API_TIMEOUT)

            if result["status"] == "ok":
                content = result.get("content", "")
                usage = result.get("usage", {})
                print(f"    OK — response: {len(content)} chars")
                if usage:
                    print(f"    Tokens: in={usage.get('prompt_tokens', '?')}, out={usage.get('completion_tokens', '?')}")
                # Print summary (last 200 chars often has the result)
                if content:
                    summary = content[-300:] if len(content) > 300 else content
                    for line in summary.split("\n")[-5:]:
                        if line.strip():
                            print(f"    > {line.strip()[:100]}")
                stats["ok"] += 1
            else:
                error = result.get("error", "unknown error")
                print(f"    FAIL — {error}", file=sys.stderr)
                stats["errors"] += 1

            # Brief pause between batches to avoid rate limiting
            if not dry_run and i < len(batches):
                time.sleep(random.uniform(1.0, 4.0))

    # ── Phase 2: Timeseries bootstrap (rough historical data) ──
    if timeseries:
        ts_kinds = [kind_filter] if kind_filter else sorted(TIMESERIES_INSTRUCTIONS.keys())
        for kind in ts_kinds:
            if kind not in targets or kind not in TIMESERIES_INSTRUCTIONS:
                continue
            kind_targets = targets[kind]
            # Smaller batches for timeseries (more API calls per entity)
            ts_batch_size = max(1, batch_size // 2)
            batches = batch_targets(kind_targets, ts_batch_size)

            print(f"\n{'='*60}")
            print(f"Timeseries: {kind} — {len(kind_targets)} targets, {len(batches)} batches")
            print(f"{'='*60}")

            for i, batch in enumerate(batches, 1):
                prompt = build_timeseries_prompt(kind, batch)
                if not prompt:
                    continue

                batch_ids = [t["id"] for t in batch]
                print(f"\n  TS Batch {i}/{len(batches)}: {batch_ids}")
                stats["batches"] += 1
                stats["targets"] += len(batch)

                if dry_run:
                    print(f"    [DRY RUN] Timeseries prompt ({len(prompt)} chars):")
                    for line in prompt[:500].split("\n"):
                        print(f"      {line}")
                    if len(prompt) > 500:
                        print(f"      ... ({len(prompt) - 500} more chars)")
                    stats["ok"] += 1
                    continue

                result = client.invoke(agent_id, prompt, timeout=API_TIMEOUT)

                if result["status"] == "ok":
                    content = result.get("content", "")
                    print(f"    OK — response: {len(content)} chars")
                    stats["ok"] += 1
                else:
                    error = result.get("error", "unknown error")
                    print(f"    FAIL — {error}", file=sys.stderr)
                    stats["errors"] += 1

                if not dry_run and i < len(batches):
                    time.sleep(random.uniform(1.0, 4.0))

    # ── Phase 3: Events bootstrap (seed current events) ──
    if events:
        # Kinds that benefit from event seeding
        events_kinds = ["countries", "stocks", "commodities", "crypto", "regions"]
        ev_kinds = [kind_filter] if kind_filter else [k for k in events_kinds if k in targets]
        for kind in ev_kinds:
            kind_targets = targets[kind]
            ev_batch_size = max(1, batch_size // 2)  # smaller batches — more tool calls
            batches = batch_targets(kind_targets, ev_batch_size)

            print(f"\n{'='*60}")
            print(f"Events: {kind} — {len(kind_targets)} targets, {len(batches)} batches")
            print(f"{'='*60}")

            for i, batch in enumerate(batches, 1):
                prompt = build_events_prompt(kind, batch)
                batch_ids = [t["id"] for t in batch]
                print(f"\n  Events Batch {i}/{len(batches)}: {batch_ids}")
                stats["batches"] += 1
                stats["targets"] += len(batch)

                if dry_run:
                    print(f"    [DRY RUN] Events prompt ({len(prompt)} chars):")
                    for line in prompt[:500].split("\n"):
                        print(f"      {line}")
                    if len(prompt) > 500:
                        print(f"      ... ({len(prompt) - 500} more chars)")
                    stats["ok"] += 1
                    continue

                result = client.invoke(agent_id, prompt, timeout=API_TIMEOUT)

                if result["status"] == "ok":
                    content = result.get("content", "")
                    print(f"    OK — response: {len(content)} chars")
                    stats["ok"] += 1
                else:
                    error = result.get("error", "unknown error")
                    print(f"    FAIL — {error}", file=sys.stderr)
                    stats["errors"] += 1

                if not dry_run and i < len(batches):
                    time.sleep(random.uniform(1.0, 4.0))

    # ── Phase 4: Plans & watchlists (seed cron-planner work) ──
    if plans:
        print(f"\n{'='*60}")
        print("Plans & Watchlists: creating initial plans for cron-planner")
        print(f"{'='*60}")

        prompt = build_plans_prompt(targets)
        stats["batches"] += 1

        if dry_run:
            print(f"  [DRY RUN] Plans prompt ({len(prompt)} chars):")
            for line in prompt[:800].split("\n"):
                print(f"    {line}")
            if len(prompt) > 800:
                print(f"    ... ({len(prompt) - 800} more chars)")
            stats["ok"] += 1
        else:
            result = client.invoke(agent_id, prompt, timeout=API_TIMEOUT)

            if result["status"] == "ok":
                content = result.get("content", "")
                print(f"  OK — response: {len(content)} chars")
                if content:
                    summary = content[-300:] if len(content) > 300 else content
                    for line in summary.split("\n")[-5:]:
                        if line.strip():
                            print(f"  > {line.strip()[:100]}")
                stats["ok"] += 1
            else:
                error = result.get("error", "unknown error")
                print(f"  FAIL — {error}", file=sys.stderr)
                stats["errors"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Bootstrap profile data via LibreChat Agents API"
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="LibreChat Agents API key (default: AUGUR_AGENTS_API_KEY from .env)",
    )
    parser.add_argument(
        "--agent-id",
        default=None,
        help="Agent ID to send prompts to (default: auto-discovered from LibreChat API)",
    )
    parser.add_argument(
        "--agent-name",
        default=DEFAULT_AGENT_NAME,
        help=f"Agent name to discover (default: {DEFAULT_AGENT_NAME})",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("LIBRECHAT_BASE_URL", DEFAULT_BASE_URL),
        help=f"LibreChat base URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--kind",
        default=None,
        help="Bootstrap only this kind (e.g., countries, stocks)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Entities per API call (default: {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--targets-file",
        default=TARGETS_FILE,
        help="Path to bootstrap-targets.json",
    )
    parser.add_argument(
        "--profiles-dir",
        default=os.environ.get("PROFILES_DIR", PROFILES_DIR),
        help="Path to profiles directory",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview prompts without calling API",
    )
    parser.add_argument(
        "--timeseries",
        action="store_true",
        help="Also bootstrap rough historical timeseries data via store_snapshot()",
    )
    parser.add_argument(
        "--events",
        action="store_true",
        help="Seed current events for bootstrapped entities via event()",
    )
    parser.add_argument(
        "--plans",
        action="store_true",
        help="Create initial plans and watchlists for cron-planner",
    )
    parser.add_argument(
        "--all-phases",
        action="store_true",
        help="Run all phases: profiles + timeseries + events + plans",
    )
    args = parser.parse_args()

    if args.all_phases:
        args.timeseries = True
        args.events = True
        args.plans = True

    # Load .env for API key (unless already in environment)
    load_env()

    # Resolve API key: --api-key > AUGUR_AGENTS_API_KEY env var
    api_key = args.api_key or os.environ.get("AUGUR_AGENTS_API_KEY", "")

    if args.kind and args.kind not in VALID_KINDS:
        print(f"ERROR: unknown kind '{args.kind}', valid: {sorted(VALID_KINDS)}", file=sys.stderr)
        sys.exit(1)

    # Validate API key (not needed for dry-run)
    if not args.dry_run and not api_key:
        print("ERROR: No API key found. Set AUGUR_AGENTS_API_KEY in .env or pass --api-key",
              file=sys.stderr)
        sys.exit(1)

    # Load targets
    targets = load_targets(args.targets_file)
    total = sum(len(v) for v in targets.values())
    print(f"Loaded {total} bootstrap targets across {len(targets)} kinds from {args.targets_file}")

    if args.dry_run:
        print("[DRY RUN MODE — no API calls will be made]\n")

    # Set up agent client
    client = AgentClient(args.base_url, api_key) if not args.dry_run else None

    # Resolve agent ID: --agent-id > auto-discover from API
    agent_id = args.agent_id
    if not agent_id and not args.dry_run:
        print(f"Discovering agent '{args.agent_name}' from {args.base_url}...")
        agent_id = client.find_agent(args.agent_name)
        if not agent_id:
            print(f"ERROR: Could not find agent '{args.agent_name}' via API. "
                  f"Seed agents first: seed-agents.py --mode bootstrap",
                  file=sys.stderr)
            sys.exit(1)
        print(f"  Found: {agent_id}")

    if not args.dry_run:
        print(f"Targeting agent {agent_id} at {args.base_url}")

    # Run bootstrap
    stats = run_bootstrap(
        client=client,
        agent_id=agent_id or "dry-run",
        targets=targets,
        profiles_dir=args.profiles_dir,
        kind_filter=args.kind,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
        timeseries=args.timeseries,
        events=args.events,
        plans=args.plans,
    )

    # Summary
    print(f"\n{'='*60}")
    print("Bootstrap Summary")
    print(f"{'='*60}")
    print(f"  Kinds processed: {stats['kinds']}")
    print(f"  Batches sent:    {stats['batches']}")
    print(f"  Total targets:   {stats['targets']}")
    print(f"  Successful:      {stats['ok']}")
    print(f"  Errors:          {stats['errors']}")

    if stats["errors"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
