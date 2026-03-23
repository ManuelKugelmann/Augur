#!/usr/bin/env python3
"""Seed LibreChat agents from agents.json definition file.

Creates or updates agents for a given user, organized by group:
  core      — data + analysis + planning (default, always seeded)
  bootstrap — bulk data bootstrapper (on-demand)
  trading   — broker agent (addon)
  news      — 4 news brand agents (addon)

Handles: login, list existing agents, create/update, wire handoff edges.
Edges to agents outside the seeded groups are silently skipped.

Usage:
    python seed-agents.py --email admin@example.com --password secret
    python seed-agents.py --email admin@example.com --password secret --bootstrap
    python seed-agents.py --email admin@example.com --password secret --group trading
    python seed-agents.py --email admin@example.com --password secret --group news --group trading
    python seed-agents.py --email admin@example.com --password secret --dry-run
"""

import argparse
import json
import os
import sys
import random
import time

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]
    if __name__ == "__main__":
        print("ERROR: httpx required. Install: pip install httpx", file=sys.stderr)
        sys.exit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "config")
AGENTS_FILE = os.path.join(CONFIG_DIR, "agents.json")
MODELS_FILE = os.path.join(CONFIG_DIR, "agent-models.json")
PROMPTS_DIR = os.path.join(CONFIG_DIR, "prompts")

ALL_GROUPS = {"core", "bootstrap", "trading", "news"}
BOOTSTRAP_MODELS_FILE = os.path.join(CONFIG_DIR, "agent-models-bootstrap.json")
DEFAULT_BASE_URL = "http://localhost:3080"

# Browser-like headers to avoid LibreChat's non-browser violation scoring.
# Without these, httpx's default User-Agent triggers NON_BROWSER_VIOLATION_SCORE
# (default 20) which can lead to silent request rejection.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


def load_prompt(agent_name: str) -> str | None:
    """Load agent instructions from prompts/<name>.md if it exists."""
    path = os.path.join(PROMPTS_DIR, f"{agent_name}.md")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    return None


def load_model_overrides(path: str | None = None) -> dict:
    """Load agent-models.json if it exists. Returns {"defaults": {}, "agents": {}}."""
    path = path or MODELS_FILE
    if not os.path.isfile(path):
        return {"defaults": {}, "agents": {}}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {
        "defaults": data.get("defaults", {}),
        "agents": data.get("agents", {}),
    }


def apply_model_overrides(agent_defs: list[dict], overrides: dict) -> int:
    """Apply model overrides to agent definitions in-place.

    Resolution order: agents.json built-in -> defaults[_layer] -> agents[_name].
    Returns count of agents whose provider/model changed.
    """
    defaults = overrides.get("defaults", {})
    per_agent = overrides.get("agents", {})
    count = 0
    for agent in agent_defs:
        layer = agent.get("_layer", "")
        name = agent.get("_name", "")
        original = (agent.get("provider"), agent.get("model"))
        # Layer default
        if layer in defaults:
            agent["provider"] = defaults[layer]["provider"]
            agent["model"] = defaults[layer]["model"]
        # Per-agent override (takes precedence)
        if name in per_agent:
            agent["provider"] = per_agent[name]["provider"]
            agent["model"] = per_agent[name]["model"]
        if (agent.get("provider"), agent.get("model")) != original:
            count += 1
    return count


def filter_by_groups(agent_defs: list[dict], groups: set[str]) -> list[dict]:
    """Return agents whose _group is in the requested set."""
    return [a for a in agent_defs if a.get("_group", "core") in groups]


def login(client: "httpx.Client", email: str, password: str) -> str:
    """Authenticate and return JWT token."""
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    if resp.status_code != 200:
        print(f"Login failed ({resp.status_code}): {resp.text}", file=sys.stderr)
        sys.exit(1)
    data = resp.json()
    token = data.get("token")
    if not token:
        print(f"Login response missing token: {data}", file=sys.stderr)
        sys.exit(1)
    return token


def list_agents(client: "httpx.Client") -> list[dict]:
    """List all agents for current user."""
    resp = client.get("/api/agents")
    if resp.status_code != 200:
        print(f"List agents failed ({resp.status_code}): {resp.text}", file=sys.stderr)
        return []
    text = resp.text.strip()
    if not text:
        return []
    try:
        data = resp.json()
    except (json.JSONDecodeError, ValueError):
        ct = resp.headers.get("content-type", "?")
        print(f"  WARNING: /api/agents returned non-JSON ({resp.status_code}, "
              f"content-type={ct}): {text[:200]}", file=sys.stderr)
        return []
    # Response may be {agents: [...]} or just [...]
    if isinstance(data, dict):
        return data.get("agents", data.get("data", []))
    if isinstance(data, list):
        return data
    return []


def find_agent_by_name(agents: list[dict], name: str) -> dict | None:
    """Find existing agent by name."""
    for a in agents:
        if a.get("name") == name:
            return a
    return None


def _safe_json(resp: "httpx.Response", label: str) -> dict:
    """Parse JSON response, returning {} on empty or invalid body."""
    text = resp.text.strip()
    if not text:
        print(f"  {label}: empty response ({resp.status_code})", file=sys.stderr)
        return {}
    try:
        data = resp.json()
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, ValueError):
        ct = resp.headers.get("content-type", "?")
        print(f"  {label}: non-JSON response ({resp.status_code}, "
              f"content-type={ct}): {text[:200]}",
              file=sys.stderr)
        return {}


def create_agent(client: "httpx.Client", agent_def: dict) -> dict:
    """Create a new agent."""
    resp = client.post("/api/agents", json=agent_def)
    if resp.status_code not in (200, 201):
        print(f"  Create failed ({resp.status_code}): {resp.text}", file=sys.stderr)
        return {}
    return _safe_json(resp, "Create")


def update_agent(client: "httpx.Client", agent_id: str, agent_def: dict) -> dict:
    """Update an existing agent."""
    payload = {**agent_def, "id": agent_id}
    resp = client.patch(f"/api/agents/{agent_id}", json=payload)
    if resp.status_code != 200:
        # Try PUT as fallback
        resp = client.put(f"/api/agents/{agent_id}", json=payload)
    if resp.status_code not in (200, 201):
        print(f"  Update failed ({resp.status_code}): {resp.text}", file=sys.stderr)
        return {}
    return _safe_json(resp, "Update")


def build_api_payload(agent_def: dict) -> dict:
    """Build API payload from seed definition (strip internal fields)."""
    return {k: v for k, v in agent_def.items() if not k.startswith("_")}


def resolve_edges(agent_defs: list[dict], id_map: dict[str, str]) -> dict[str, list]:
    """Resolve _name references in edges to GraphEdge objects.

    LibreChat edges are objects: {from: agent_id, to: agent_id, edgeType: "handoff"}
    Edges to agents not in id_map (not seeded) are silently skipped.
    """
    resolved = {}
    for a in agent_defs:
        internal_name = a["_name"]
        from_id = id_map.get(internal_name)
        if not from_id:
            continue
        edge_names = a.get("edges", [])
        edge_objects = []
        for name in edge_names:
            if name in id_map:
                edge_objects.append({
                    "from": from_id,
                    "to": id_map[name],
                    "edgeType": "handoff",
                })
            # Silently skip edges to agents outside seeded groups
        resolved[internal_name] = edge_objects
    return resolved


def main():
    parser = argparse.ArgumentParser(description="Seed LibreChat agents")
    parser.add_argument("--email", required=True, help="LibreChat user email")
    parser.add_argument("--password", required=True, help="LibreChat user password")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="LibreChat base URL")
    parser.add_argument("--group", action="append", dest="groups", metavar="GROUP",
                        help="Agent groups to seed (core, bootstrap, trading, news). "
                             "Core is always included. Repeat for multiple: "
                             "--group trading --group news")
    parser.add_argument("--all", action="store_true", help="Seed all groups")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without executing")
    parser.add_argument("--agents-file", default=AGENTS_FILE, help="Path to agents.json")
    parser.add_argument("--bootstrap", action="store_true",
                        help="Bootstrap mode: include bootstrap group and use Qwen-heavy "
                             "models (agent-models-bootstrap.json) for initial data seeding")
    parser.add_argument("--models-file", default=None,
                        help="Path to agent-models JSON file (overrides default)")
    parser.add_argument("--no-model-overrides", action="store_true",
                        help="Ignore agent-models.json, use agents.json models as-is")
    parser.add_argument("--export", action="store_true",
                        help="Export current agent configs from LibreChat API as JSON")
    parser.add_argument("--lc-wait", type=int, default=0, metavar="SECS",
                        help="Wait up to SECS seconds for LibreChat to become reachable")
    args = parser.parse_args()

    # Determine which groups to seed (core is always included)
    if args.all:
        groups = ALL_GROUPS.copy()
    elif args.groups:
        groups = {"core"} | {g for g in args.groups if g in ALL_GROUPS}
        invalid = {g for g in args.groups if g not in ALL_GROUPS}
        if invalid:
            print(f"WARNING: unknown groups ignored: {invalid} "
                  f"(valid: {', '.join(sorted(ALL_GROUPS))})", file=sys.stderr)
    else:
        groups = {"core"}
    if args.bootstrap:
        groups.add("bootstrap")

    # Load agent definitions
    with open(args.agents_file) as f:
        all_defs = json.load(f)

    # Filter to requested groups
    agent_defs = filter_by_groups(all_defs, groups)

    # Overlay instructions from prompts/*.md (takes precedence over agents.json)
    prompt_count = 0
    for agent_def in agent_defs:
        prompt = load_prompt(agent_def["_name"])
        if prompt:
            agent_def["instructions"] = prompt
            prompt_count += 1

    # Resolve which models file to use: --models-file > --bootstrap > default
    if not args.no_model_overrides:
        if args.models_file:
            models_path = args.models_file
        elif args.bootstrap:
            models_path = BOOTSTRAP_MODELS_FILE
        else:
            models_path = MODELS_FILE
        overrides = load_model_overrides(models_path)
        override_count = apply_model_overrides(agent_defs, overrides)
    else:
        models_path = None
        override_count = 0

    group_str = ", ".join(sorted(groups))
    print(f"Loaded {len(agent_defs)} agents (groups: {group_str}) from {args.agents_file}")
    if prompt_count:
        print(f"  ({prompt_count} instructions loaded from {PROMPTS_DIR}/)")
    if override_count:
        print(f"  ({override_count} model overrides applied from {models_path})")

    if args.dry_run:
        print(f"\n[DRY RUN] Would create/update these agents (groups: {group_str}):")
        for a in agent_defs:
            edges = a.get("edges", [])
            edge_str = f" -> [{', '.join(edges)}]" if edges else ""
            print(f"  [{a['_group']}:{a['_layer']}] {a['_name']}: {a['name']} "
                  f"({a['provider']}/{a['model']}){edge_str}")
        return

    # Connect and authenticate
    client = httpx.Client(base_url=args.base_url, timeout=30, headers=BROWSER_HEADERS)

    # Pre-flight connectivity check (with optional wait)
    deadline = time.monotonic() + args.lc_wait
    attempt = 0
    print(f"\nConnecting to {args.base_url}..." +
          (f" (waiting up to {args.lc_wait}s)" if args.lc_wait else ""))
    while True:
        try:
            client.get("/")
            break
        except httpx.ConnectError:
            attempt += 1
            if time.monotonic() >= deadline:
                waited = f" after waiting {args.lc_wait}s" if args.lc_wait else ""
                print(f"ERROR: Cannot connect to {args.base_url}{waited}\n"
                      f"  Is LibreChat running? Check with: systemctl --user status librechat",
                      file=sys.stderr)
                sys.exit(1)
            delay = min(2 ** attempt, 10)
            remaining = deadline - time.monotonic()
            delay = min(delay, remaining)
            if delay > 0:
                print(f"  waiting ({attempt})...", flush=True)
                time.sleep(delay)

    print(f"Logging in as {args.email}...")
    token = login(client, args.email, args.password)
    client.headers["Authorization"] = f"Bearer {token}"
    print("  OK")

    # List existing agents (includes agents from all groups already on server)
    existing = list_agents(client)

    # --export: dump current agent configs from LibreChat API and exit
    if args.export:
        name_to_meta = {a["name"]: {k: v for k, v in a.items() if k.startswith("_")}
                        for a in all_defs}
        export_data = []
        for ea in existing:
            entry = {
                "id": ea.get("id"),
                "name": ea.get("name"),
                "provider": ea.get("provider"),
                "model": ea.get("model"),
                "tools": ea.get("tools", []),
            }
            meta = name_to_meta.get(ea.get("name"), {})
            entry.update(meta)
            export_data.append(entry)
        print(json.dumps(export_data, indent=2))
        client.close()
        return

    print(f"Found {len(existing)} existing agents")

    # Build id_map from existing agents too (for cross-group edge resolution)
    # This way, if trading was seeded previously and we're now seeding news,
    # edges to trader will still resolve.
    id_map: dict[str, str] = {}
    name_to_internal = {a["name"]: a["_name"] for a in all_defs}
    for ea in existing:
        internal = name_to_internal.get(ea.get("name"))
        if internal:
            id_map[internal] = ea["id"]

    # Phase 1: Create/update agents in requested groups
    for agent_def in agent_defs:
        internal_name = agent_def["_name"]
        payload = build_api_payload(agent_def)
        # Remove edges for first pass (need IDs to resolve)
        payload.pop("edges", None)

        existing_agent = find_agent_by_name(existing, agent_def["name"])

        if existing_agent:
            agent_id = existing_agent["id"]
            print(f"  UPDATE [{agent_def['_group']}:{agent_def['_layer']}] {internal_name} ({agent_id})")
            result = update_agent(client, agent_id, payload)
        else:
            print(f"  CREATE [{agent_def['_group']}:{agent_def['_layer']}] {internal_name}")
            result = create_agent(client, payload)

        if result:
            agent_id = result.get("id", existing_agent["id"] if existing_agent else "?")
            id_map[internal_name] = agent_id
            print(f"    -> {agent_id}")
        else:
            print(f"    -> FAILED", file=sys.stderr)

        # Brief pause to avoid rate limiting
        time.sleep(random.uniform(0.05, 0.3))

    # Phase 2: Wire handoff edges (now we have all IDs)
    print(f"\nWiring handoff edges...")
    resolved = resolve_edges(agent_defs, id_map)

    for agent_def in agent_defs:
        internal_name = agent_def["_name"]
        edge_objects = resolved.get(internal_name, [])

        if not edge_objects:
            continue

        agent_id = id_map.get(internal_name)
        if not agent_id:
            continue

        edge_names = [e for e in agent_def.get("edges", []) if e in id_map]
        target_ids = [e["to"] for e in edge_objects]
        print(f"  {internal_name}: {edge_names} -> {target_ids}")
        update_agent(client, agent_id, {"edges": edge_objects})
        time.sleep(random.uniform(0.05, 0.3))

    # Summary
    seeded_names = [a["_name"] for a in agent_defs if a["_name"] in id_map]
    print(f"\nDone! {len(seeded_names)} agents seeded (groups: {group_str}).")
    print(f"\nAgent IDs:")
    for name in seeded_names:
        print(f"  {name}: {id_map[name]}")

    client.close()


if __name__ == "__main__":
    main()
