#!/usr/bin/env python3
"""Seed LibreChat agents from agents.json definition file.

Creates or updates all 11 multi-agent architecture agents for a given user.
Handles: login, list existing agents, create/update, wire handoff edges.

Usage:
    python seed-agents.py --email admin@example.com --password secret
    python seed-agents.py --email admin@example.com --password secret --base-url http://localhost:3080
    python seed-agents.py --email admin@example.com --password secret --dry-run
"""

import argparse
import json
import os
import sys
import time

try:
    import httpx
except ImportError:
    print("ERROR: httpx required. Install: pip install httpx", file=sys.stderr)
    sys.exit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "config")
AGENTS_FILE = os.path.join(CONFIG_DIR, "agents.json")

DEFAULT_BASE_URL = "http://localhost:3080"


def login(client: httpx.Client, email: str, password: str) -> str:
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


def list_agents(client: httpx.Client) -> list[dict]:
    """List all agents for current user."""
    resp = client.get("/api/agents")
    if resp.status_code != 200:
        print(f"List agents failed ({resp.status_code}): {resp.text}", file=sys.stderr)
        return []
    data = resp.json()
    # Response may be {agents: [...]} or just [...]
    if isinstance(data, dict):
        return data.get("agents", data.get("data", []))
    return data


def find_agent_by_name(agents: list[dict], name: str) -> dict | None:
    """Find existing agent by name."""
    for a in agents:
        if a.get("name") == name:
            return a
    return None


def create_agent(client: httpx.Client, agent_def: dict) -> dict:
    """Create a new agent."""
    resp = client.post("/api/agents", json=agent_def)
    if resp.status_code not in (200, 201):
        print(f"  Create failed ({resp.status_code}): {resp.text}", file=sys.stderr)
        return {}
    return resp.json()


def update_agent(client: httpx.Client, agent_id: str, agent_def: dict) -> dict:
    """Update an existing agent."""
    payload = {**agent_def, "id": agent_id}
    resp = client.patch(f"/api/agents/{agent_id}", json=payload)
    if resp.status_code != 200:
        # Try PUT as fallback
        resp = client.put(f"/api/agents/{agent_id}", json=payload)
    if resp.status_code not in (200, 201):
        print(f"  Update failed ({resp.status_code}): {resp.text}", file=sys.stderr)
        return {}
    return resp.json()


def build_api_payload(agent_def: dict) -> dict:
    """Build API payload from seed definition (strip internal fields)."""
    return {k: v for k, v in agent_def.items() if not k.startswith("_")}


def resolve_edges(agent_defs: list[dict], id_map: dict[str, str]) -> dict[str, list]:
    """Resolve _name references in edges to GraphEdge objects.

    LibreChat edges are objects: {from: agent_id, to: agent_id, edgeType: "handoff"}
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
            else:
                print(f"  WARNING: edge target '{name}' not found for {internal_name}",
                      file=sys.stderr)
        resolved[internal_name] = edge_objects
    return resolved


def main():
    parser = argparse.ArgumentParser(description="Seed LibreChat agents")
    parser.add_argument("--email", required=True, help="LibreChat user email")
    parser.add_argument("--password", required=True, help="LibreChat user password")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="LibreChat base URL")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without executing")
    parser.add_argument("--agents-file", default=AGENTS_FILE, help="Path to agents.json")
    args = parser.parse_args()

    # Load agent definitions
    with open(args.agents_file) as f:
        agent_defs = json.load(f)

    print(f"Loaded {len(agent_defs)} agent definitions from {args.agents_file}")

    if args.dry_run:
        print("\n[DRY RUN] Would create/update these agents:")
        for a in agent_defs:
            edges = a.get("edges", [])
            edge_str = f" -> [{', '.join(edges)}]" if edges else ""
            print(f"  [{a['_layer']}] {a['_name']}: {a['name']} ({a['model']}){edge_str}")
        return

    # Connect and authenticate
    client = httpx.Client(base_url=args.base_url, timeout=30)

    print(f"\nLogging in to {args.base_url} as {args.email}...")
    token = login(client, args.email, args.password)
    client.headers["Authorization"] = f"Bearer {token}"
    print("  OK")

    # List existing agents
    existing = list_agents(client)
    print(f"Found {len(existing)} existing agents")

    # Phase 1: Create/update all agents (without edges, to get IDs first)
    id_map: dict[str, str] = {}  # _name -> agent_id

    for agent_def in agent_defs:
        internal_name = agent_def["_name"]
        payload = build_api_payload(agent_def)
        # Remove edges for first pass (need IDs to resolve)
        payload.pop("edges", None)

        existing_agent = find_agent_by_name(existing, agent_def["name"])

        if existing_agent:
            agent_id = existing_agent["id"]
            print(f"  UPDATE [{agent_def['_layer']}] {internal_name} ({agent_id})")
            result = update_agent(client, agent_id, payload)
        else:
            print(f"  CREATE [{agent_def['_layer']}] {internal_name}")
            result = create_agent(client, payload)

        if result:
            agent_id = result.get("id", existing_agent["id"] if existing_agent else "?")
            id_map[internal_name] = agent_id
            print(f"    -> {agent_id}")
        else:
            print(f"    -> FAILED", file=sys.stderr)

        # Brief pause to avoid rate limiting
        time.sleep(0.1)

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

        edge_names = agent_def.get("edges", [])
        target_ids = [e["to"] for e in edge_objects]
        print(f"  {internal_name}: {edge_names} -> {target_ids}")
        update_agent(client, agent_id, {"edges": edge_objects})
        time.sleep(0.1)

    # Summary
    print(f"\nDone! {len(id_map)} agents seeded.")
    print(f"\nAgent IDs (for modelSpecs in librechat.yaml):")
    for name, aid in id_map.items():
        print(f"  {name}: {aid}")

    client.close()


if __name__ == "__main__":
    main()
