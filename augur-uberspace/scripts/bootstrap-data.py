#!/usr/bin/env python3
"""Bootstrap data via the bootstrap agent.

Single command, all phases, one agent call per kind. Safe to re-run —
each run deepens data (enriches existing profiles, adds new events,
updates stale plans). Rate limits handled by agent_client retry logic.

Phases: profiles → timeseries → events → plans

Usage:
    python bootstrap-data.py --dry-run          # preview prompts
    python bootstrap-data.py                    # all kinds, all phases
    python bootstrap-data.py --kind countries   # one kind only
    python bootstrap-data.py --phase profiles   # one phase only
    python bootstrap-data.py                    # re-run to deepen data
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from agent_client import AgentClient, load_env  # noqa: E402

TARGETS_FILE = os.path.join(SCRIPT_DIR, "bootstrap-targets.json")
REPO_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
PROFILES_DIR = os.path.join(REPO_ROOT, "profiles")

DEFAULT_BASE_URL = "http://localhost:3080"
DEFAULT_AGENT_NAME = "bootstrap"
# Long timeout — agent makes many tool calls per kind
API_TIMEOUT = 600  # 10 min per kind

VALID_KINDS = {
    "countries", "stocks", "etfs", "crypto", "indices", "sources",
    "commodities", "crops", "materials", "products", "companies",
    "regions",
}

ALL_PHASES = ["profiles", "timeseries", "events", "plans"]

# Kinds that have timeseries bootstrap instructions
TIMESERIES_KINDS = {"countries", "stocks", "etfs", "commodities", "crops"}

# Kinds that benefit from event seeding
EVENTS_KINDS = {"countries", "stocks", "commodities", "crypto", "regions"}

# ── Kind-specific instructions ──────────────────────────────

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

TIMESERIES_INSTRUCTIONS = {
    "countries": (
        "Fetch rough historical economic data and store as snapshots:\n"
        "- Use econ_world_bank_indicator for GDP, GDP growth, inflation, unemployment (annual, last 5 years)\n"
        "- Use econ_fred_series for US-specific time series\n"
        "- Use econ_imf_weo for forecasts\n"
        "Call `store_snapshot(kind='countries', entity=ID, type='macro', "
        "data={year, gdp, gdp_growth, inflation, unemployment, ...}, region=REGION)`. One snapshot per year."
    ),
    "stocks": (
        "Fetch recent price + technical indicators:\n"
        "- Use ta_analyze_full for current OHLCV + indicators\n"
        "Call `store_snapshot(kind='stocks', entity=ID, type='indicators', data={...}, region=REGION)`."
    ),
    "etfs": (
        "Fetch current data and store as snapshot:\n"
        "- Use ta_analyze_full for current OHLCV + indicators\n"
        "Call `store_snapshot(kind='etfs', entity=ID, type='indicators', data={...}, region=REGION)`."
    ),
    "commodities": (
        "Fetch recent price/production data:\n"
        "- Use commodities_eia_series for energy commodities\n"
        "- Use agri_faostat_data for agricultural commodities\n"
        "Call `store_snapshot(kind='commodities', entity=ID, type='price', data={...}, region='global')`."
    ),
    "crops": (
        "Fetch recent production data:\n"
        "- Use agri_faostat_data for global production/trade\n"
        "- Use agri_usda_nass for US production\n"
        "Call `store_snapshot(kind='crops', entity=ID, type='production', "
        "data={year, production_mt, area_ha, yield_kg_ha, ...}, region='global')`. One snapshot per year."
    ),
}

EVENTS_INSTRUCTIONS = {
    "countries": (
        "Delegate to osint-data to scrape GDELT, disaster feeds, and conflict trackers. "
        "Look for: active conflicts, sanctions, elections, policy changes, natural disasters, "
        "economic crises. Also delegate to signals-data for trending news."
    ),
    "stocks": (
        "Delegate to market-data for recent earnings surprises, significant price moves (>3% daily), "
        "IPOs, delistings, rating changes. Delegate to signals-data for trending Reddit/HN discussions."
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


# ── Prompt builders ─────────────────────────────────────────

def load_targets(targets_file: str) -> dict:
    """Load bootstrap targets from JSON file."""
    with open(targets_file) as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if not k.startswith("_")}


def find_existing_profiles(profiles_dir: str, kind: str) -> set[str]:
    """Find profile IDs that already exist on disk."""
    existing = set()
    if not os.path.isdir(profiles_dir):
        return existing
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
                existing.add(f[:-5])
    return existing


def count_all_profiles(profiles_dir: str) -> dict[str, int]:
    """Count existing profiles per kind on disk."""
    counts: dict[str, int] = {}
    if not os.path.isdir(profiles_dir):
        return counts
    for region_dir in os.listdir(profiles_dir):
        region_path = os.path.join(profiles_dir, region_dir)
        if not os.path.isdir(region_path) or region_dir.startswith((".", "_")):
            continue
        if region_dir in ("SCHEMAS",):
            continue
        for kind_dir in os.listdir(region_path):
            kind_path = os.path.join(region_path, kind_dir)
            if not os.path.isdir(kind_path):
                continue
            n = sum(1 for f in os.listdir(kind_path)
                    if f.endswith(".json") and not f.startswith("_"))
            counts[kind_dir] = counts.get(kind_dir, 0) + n
    return counts


def print_data_stats(profiles_dir: str, targets: dict, label: str = ""):
    """Print profile counts vs target counts."""
    counts = count_all_profiles(profiles_dir)
    print(f"\n  {'Data' if not label else label}:")
    print(f"  {'Kind':<15} {'Profiles':>8} / {'Targets':>7}  {'Coverage':>8}")
    print(f"  {'─'*15} {'─'*8} {'─'*2} {'─'*7}  {'─'*8}")
    total_profiles = 0
    total_targets = 0
    for kind in sorted(targets.keys()):
        n_profiles = counts.get(kind, 0)
        n_targets = len(targets[kind])
        pct = f"{n_profiles / n_targets * 100:.0f}%" if n_targets else "—"
        print(f"  {kind:<15} {n_profiles:>8} / {n_targets:>7}  {pct:>8}")
        total_profiles += n_profiles
        total_targets += n_targets
    print(f"  {'─'*15} {'─'*8} {'─'*2} {'─'*7}  {'─'*8}")
    pct = f"{total_profiles / total_targets * 100:.0f}%" if total_targets else "—"
    print(f"  {'TOTAL':<15} {total_profiles:>8} / {total_targets:>7}  {pct:>8}")


def _entity_list(targets: list[dict]) -> str:
    """Format entity list for prompts."""
    return "\n".join(f"- **{t['id']}** (region: {t['region']})" for t in targets)


def build_profiles_prompt(kind: str, targets: list[dict], existing_ids: set[str]) -> str:
    """Build profile bootstrap prompt for all targets of a kind."""
    instructions = KIND_INSTRUCTIONS.get(kind, "Populate all schema fields accurately.")
    new_targets = [t for t in targets if t["id"] not in existing_ids]
    enrich_targets = [t for t in targets if t["id"] in existing_ids]

    parts = [
        f"## Profile Bootstrap: {kind} ({len(targets)} entities)\n",
        "Bootstrap profile data for the trading signals platform. "
        "Delegate to L1 data agents, then call `store_put_profile()` for each entity. "
        "This may be a re-run — enrich existing profiles with deeper/fresher data, "
        "don't skip entities just because they already exist.\n",
        f"### Data gathering instructions\n{instructions}\n",
    ]

    if enrich_targets:
        parts.append(
            f"### Profiles to ENRICH ({len(enrich_targets)} existing)\n"
            "Read each with `store_get_profile()`, then update with fresh data.\n"
        )
        parts.append(_entity_list(enrich_targets))

    if new_targets:
        parts.append(
            f"\n### Profiles to CREATE ({len(new_targets)} new)\n"
        )
        parts.append(_entity_list(new_targets))

    parts.extend([
        "\n### Rules",
        f"1. Call `store_put_profile(kind=\"{kind}\", id=ID, data={{...}}, region=REGION)` for each.",
        "2. Set `_sources` array to actual data sources used.",
        "3. Do NOT set `_placeholder: true`.",
        "4. Include `tags` array.",
        "5. Process ALL entities. Report: {created: N, enriched: N, errors: N}.",
        "6. If a tool fails, skip that entity and continue.",
    ])

    return "\n".join(parts)


def build_timeseries_prompt(kind: str, targets: list[dict]) -> str | None:
    """Build timeseries bootstrap prompt for all targets of a kind."""
    instructions = TIMESERIES_INSTRUCTIONS.get(kind)
    if not instructions:
        return None

    return "\n".join([
        f"## Timeseries Bootstrap: {kind} ({len(targets)} entities)\n",
        "Fetch historical data via L1 agents, store as snapshots.\n",
        f"### Instructions\n{instructions}\n",
        f"### Entities\n{_entity_list(targets)}\n",
        "### Rules",
        "1. Use MCP data tools to fetch REAL data — do not fabricate.",
        "2. Store each data point via `store_snapshot()`.",
        "3. Skip entities where tools fail — continue with the rest.",
        "4. Rough/approximate data is fine — this is seed data.",
        "5. Process ALL entities. Report: {snapshots_stored: N, errors: N}.",
    ])


def build_events_prompt(kind: str, targets: list[dict]) -> str:
    """Build events bootstrap prompt for all targets of a kind."""
    instructions = EVENTS_INSTRUCTIONS.get(kind,
        f"Delegate to appropriate L1 agents to find current events affecting these {kind}.")

    return "\n".join([
        f"## Events Bootstrap: {kind} ({len(targets)} entities)\n",
        "Seed current events by delegating to L1 agents, then call "
        "`event(subtype, summary, data, severity, countries, entities, region, source)`. "
        "This may be a re-run — focus on NEW events since the last run. "
        "Check `recent_events()` first to avoid duplicating existing events.\n",
        f"### Instructions\n{instructions}\n",
        f"### Entities\n{_entity_list(targets)}\n",
        "### Rules",
        "1. Only store REAL current events — do not fabricate.",
        "2. Severity: routine=low, notable=medium, major=high, crisis=critical.",
        "3. Link events via `countries` (ISO3) and `entities` (IDs) arrays.",
        "4. Set `source` to data origin (gdelt, reddit, rss, finance, google_news).",
        "5. Valid subtypes: earthquake, volcano, flood, drought, wildfire, conflict, "
        "sanctions, election, policy, tariff, earnings, ipo, default, signal_change, "
        "price_spike, supply_disruption, transport, epidemic, sentiment_shift.",
        "6. Skip entities with no current events.",
        "7. Report: {events_stored: N, by_severity: {...}, errors: N}.",
    ])


def build_plans_prompt(targets: dict) -> str:
    """Build prompt to create initial plans and watchlists."""
    kind_summary = ", ".join(f"{k}: {len(v)}" for k, v in sorted(targets.items()))

    return (
        "## Bootstrap Plans & Watchlists\n\n"
        "Create or update research plans and watchlists for cron-planner. "
        "First, read existing plans (`get_notes(kind=\"plan\")`) and watchlists "
        "(`get_notes(kind=\"watchlist\")`). Update existing ones with fresh data "
        "rather than creating duplicates.\n\n"
        f"**Bootstrapped entity counts**: {kind_summary}\n\n"
        "### Plans to create (`save_note` with `kind=\"plan\"`):\n\n"
        "1. **Daily data refresh** — schedule per kind: stocks 2x daily, "
        "commodities/crypto daily, countries/regions weekly, sources monthly.\n"
        "2. **High-priority entities** — use `recent_events()` to find entities "
        "with severity >= medium. Include reason and check frequency.\n"
        "3. **Coverage gaps** — read bootstrap journal logs "
        "(`get_notes(kind=\"journal\", tag=\"bootstrap\")`) and list thin areas.\n"
        "4. **Analysis cadence** — L2 analysts after daily refresh, "
        "L3 synthesizer on high-severity events and weekly deep-dive.\n\n"
        "### Watchlists to create (`save_note` with `kind=\"watchlist\"`):\n\n"
        "1. **Market movers** — highest volatility stocks/ETFs/crypto.\n"
        "2. **Geopolitical hotspots** — active conflicts, sanctions, disasters.\n"
        "3. **Supply chain risks** — disrupted commodities/materials.\n\n"
        "### Rules\n"
        "- Tag plans with `[\"bootstrap\", \"initial\"]`, watchlists with `[\"bootstrap\", \"watchlist\"]`.\n"
        "- Include specific entity IDs in watchlists.\n"
        "- If no events exist yet, base watchlists on profile risk_factors.\n"
        "- Report: {plans_created: N, watchlists_created: N}."
    )


# ── Logging helpers ─────────────────────────────────────────

def log_phase(phase: str, kind: str = "", count: int = 0):
    """Print phase/kind header."""
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    if kind:
        print(f"\n[{ts}] ── {phase}: {kind} ({count} entities) ──")
    else:
        print(f"\n[{ts}] ── {phase} ──")


def log_result(result: dict, label: str = "") -> bool:
    """Print result summary. Returns True if ok."""
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    prefix = f"  {label}: " if label else "  "

    if result["status"] == "ok":
        content = result.get("content", "")
        usage = result.get("usage", {})
        tok_in = usage.get("prompt_tokens", "?")
        tok_out = usage.get("completion_tokens", "?")
        print(f"[{ts}]{prefix}OK ({len(content)} chars, {tok_in}→{tok_out} tokens)")
        # Print last few lines of response (usually the summary)
        if content:
            for line in content.strip().split("\n")[-3:]:
                if line.strip():
                    print(f"         {line.strip()[:120]}")
        return True
    else:
        error = result.get("error", "unknown")
        print(f"[{ts}]{prefix}FAIL — {error}", file=sys.stderr)
        return False


def log_dry_run(prompt: str, label: str = ""):
    """Print dry-run prompt preview."""
    prefix = f"  {label}: " if label else "  "
    print(f"{prefix}[DRY RUN] {len(prompt)} chars")
    # Show first 3 non-empty lines
    shown = 0
    for line in prompt.split("\n"):
        if line.strip() and shown < 3:
            print(f"    {line.strip()[:100]}")
            shown += 1


# ── Main runner ─────────────────────────────────────────────

def run_bootstrap(
    client: AgentClient | None,
    agent_id: str,
    targets: dict,
    profiles_dir: str,
    kind_filter: str | None = None,
    phases: list[str] | None = None,
    dry_run: bool = False,
) -> dict:
    """Run bootstrap phases. One agent call per kind per phase."""
    phases = phases or ALL_PHASES
    stats = {"calls": 0, "ok": 0, "errors": 0, "phases": []}
    start = time.monotonic()

    kinds = [kind_filter] if kind_filter else sorted(
        k for k in targets if k in VALID_KINDS)

    for phase in phases:
        stats["phases"].append(phase)

        if phase == "profiles":
            for kind in kinds:
                kind_targets = targets.get(kind, [])
                if not kind_targets:
                    continue
                existing = find_existing_profiles(profiles_dir, kind)
                new = sum(1 for t in kind_targets if t["id"] not in existing)
                log_phase("Profiles", kind, len(kind_targets))
                print(f"  {new} new, {len(kind_targets) - new} enrich")

                prompt = build_profiles_prompt(kind, kind_targets, existing)
                stats["calls"] += 1

                if dry_run:
                    log_dry_run(prompt, kind)
                    stats["ok"] += 1
                else:
                    result = client.invoke(agent_id, prompt, timeout=API_TIMEOUT)
                    if log_result(result, kind):
                        stats["ok"] += 1
                    else:
                        stats["errors"] += 1

        elif phase == "timeseries":
            for kind in kinds:
                if kind not in TIMESERIES_KINDS:
                    continue
                kind_targets = targets.get(kind, [])
                if not kind_targets:
                    continue
                log_phase("Timeseries", kind, len(kind_targets))

                prompt = build_timeseries_prompt(kind, kind_targets)
                if not prompt:
                    continue
                stats["calls"] += 1

                if dry_run:
                    log_dry_run(prompt, kind)
                    stats["ok"] += 1
                else:
                    result = client.invoke(agent_id, prompt, timeout=API_TIMEOUT)
                    if log_result(result, kind):
                        stats["ok"] += 1
                    else:
                        stats["errors"] += 1

        elif phase == "events":
            for kind in kinds:
                if kind not in EVENTS_KINDS:
                    continue
                kind_targets = targets.get(kind, [])
                if not kind_targets:
                    continue
                log_phase("Events", kind, len(kind_targets))

                prompt = build_events_prompt(kind, kind_targets)
                stats["calls"] += 1

                if dry_run:
                    log_dry_run(prompt, kind)
                    stats["ok"] += 1
                else:
                    result = client.invoke(agent_id, prompt, timeout=API_TIMEOUT)
                    if log_result(result, kind):
                        stats["ok"] += 1
                    else:
                        stats["errors"] += 1

        elif phase == "plans":
            log_phase("Plans & Watchlists")
            prompt = build_plans_prompt(targets)
            stats["calls"] += 1

            if dry_run:
                log_dry_run(prompt, "plans")
                stats["ok"] += 1
            else:
                result = client.invoke(agent_id, prompt, timeout=API_TIMEOUT)
                if log_result(result, "plans"):
                    stats["ok"] += 1
                else:
                    stats["errors"] += 1

    stats["elapsed"] = round(time.monotonic() - start, 1)
    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Bootstrap data via the bootstrap agent"
    )
    parser.add_argument(
        "--api-key", default=None,
        help="LibreChat API key (default: AUGUR_AGENTS_API_KEY from .env)",
    )
    parser.add_argument(
        "--agent-id", default=None,
        help="Agent ID (default: auto-discovered)",
    )
    parser.add_argument(
        "--agent-name", default=DEFAULT_AGENT_NAME,
        help=f"Agent name to discover (default: {DEFAULT_AGENT_NAME})",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("LIBRECHAT_BASE_URL", DEFAULT_BASE_URL),
        help=f"LibreChat base URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--kind", default=None,
        help="Bootstrap only this kind (e.g., countries, stocks)",
    )
    parser.add_argument(
        "--phase", default=None, choices=ALL_PHASES,
        help="Run only this phase (default: all phases)",
    )
    parser.add_argument(
        "--targets-file", default=TARGETS_FILE,
        help="Path to bootstrap-targets.json",
    )
    parser.add_argument(
        "--profiles-dir",
        default=os.environ.get("PROFILES_DIR", PROFILES_DIR),
        help="Path to profiles directory",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview prompts without calling API",
    )
    args = parser.parse_args()

    if args.kind and args.kind not in VALID_KINDS:
        print(f"ERROR: unknown kind '{args.kind}', valid: {sorted(VALID_KINDS)}",
              file=sys.stderr)
        sys.exit(1)

    load_env()
    api_key = args.api_key or os.environ.get("AUGUR_AGENTS_API_KEY", "")

    if not args.dry_run and not api_key:
        print("ERROR: No API key. Set AUGUR_AGENTS_API_KEY in .env or pass --api-key",
              file=sys.stderr)
        sys.exit(1)

    targets = load_targets(args.targets_file)
    total = sum(len(v) for v in targets.values())

    phases = [args.phase] if args.phase else ALL_PHASES

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"Bootstrap started at {ts}")
    print(f"  Targets: {total} entities across {len(targets)} kinds")
    print(f"  Phases:  {' → '.join(phases)}")
    if args.kind:
        print(f"  Filter:  {args.kind} only")
    if args.dry_run:
        print("  Mode:    DRY RUN (no API calls)")

    # Before stats
    print_data_stats(args.profiles_dir, targets, "Before")

    client = None
    agent_id = args.agent_id or "dry-run"

    if not args.dry_run:
        client = AgentClient(args.base_url, api_key)
        if not args.agent_id:
            print(f"  Agent:   discovering '{args.agent_name}'...")
            agent_id = client.find_agent(args.agent_name)
            if not agent_id:
                print(f"ERROR: Agent '{args.agent_name}' not found. "
                      f"Run: seed-agents.py --mode bootstrap", file=sys.stderr)
                sys.exit(1)
        print(f"  Agent:   {agent_id} @ {args.base_url}")

    stats = run_bootstrap(
        client=client,
        agent_id=agent_id,
        targets=targets,
        profiles_dir=args.profiles_dir,
        kind_filter=args.kind,
        phases=phases,
        dry_run=args.dry_run,
    )

    # After stats
    print_data_stats(args.profiles_dir, targets, "After")

    # Summary
    print(f"\n{'='*50}")
    print(f"Bootstrap complete in {stats['elapsed']}s")
    print(f"  Phases: {' → '.join(stats['phases'])}")
    print(f"  Calls:  {stats['calls']} ({stats['ok']} ok, {stats['errors']} errors)")
    print(f"{'='*50}")

    if stats["errors"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
