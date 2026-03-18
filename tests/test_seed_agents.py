"""Tests for seed-agents.py — agent definition loading, filtering, payload building, edge resolution."""

import json
import os
import sys
import importlib
import types

import pytest


# ---------------------------------------------------------------------------
# Import seed-agents.py as a module (filename contains a hyphen)
# ---------------------------------------------------------------------------

SCRIPT_PATH = os.path.join(
    os.path.dirname(__file__), os.pardir,
    "augur-uberspace", "scripts", "seed-agents.py",
)
SCRIPT_PATH = os.path.normpath(SCRIPT_PATH)


@pytest.fixture(scope="module")
def seed_agents():
    """Import seed-agents.py as a module."""
    spec = importlib.util.spec_from_file_location("seed_agents", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Sample agent definitions (mirrors structure of agents.json)
# ---------------------------------------------------------------------------

SAMPLE_AGENTS = [
    {
        "_name": "market-data",
        "_layer": "L1",
        "_group": "core",
        "name": "Market Data",
        "model": "claude-haiku-4-5-20251001",
        "instructions": "Scrape market data.",
        "edges": ["analyst"],
    },
    {
        "_name": "analyst",
        "_layer": "L2",
        "_group": "core",
        "name": "Analyst",
        "model": "claude-haiku-4-5-20251001",
        "instructions": "Analyze data.",
        "edges": [],
    },
    {
        "_name": "trader",
        "_layer": "L2",
        "_group": "trading",
        "name": "Trader",
        "model": "claude-haiku-4-5-20251001",
        "instructions": "Execute trades.",
        "edges": ["analyst"],
    },
    {
        "_name": "news-us",
        "_layer": "L1",
        "_group": "news",
        "name": "US News",
        "model": "claude-haiku-4-5-20251001",
        "instructions": "US news.",
        "edges": [],
    },
]


# ---------------------------------------------------------------------------
# Tests: filter_by_groups
# ---------------------------------------------------------------------------


class TestFilterByGroups:
    def test_core_only(self, seed_agents):
        result = seed_agents.filter_by_groups(SAMPLE_AGENTS, {"core"})
        names = {a["_name"] for a in result}
        assert names == {"market-data", "analyst"}

    def test_trading_group(self, seed_agents):
        result = seed_agents.filter_by_groups(SAMPLE_AGENTS, {"trading"})
        assert len(result) == 1
        assert result[0]["_name"] == "trader"

    def test_multiple_groups(self, seed_agents):
        result = seed_agents.filter_by_groups(SAMPLE_AGENTS, {"core", "news"})
        names = {a["_name"] for a in result}
        assert names == {"market-data", "analyst", "news-us"}

    def test_all_groups(self, seed_agents):
        result = seed_agents.filter_by_groups(SAMPLE_AGENTS, {"core", "trading", "news"})
        assert len(result) == len(SAMPLE_AGENTS)

    def test_empty_groups(self, seed_agents):
        result = seed_agents.filter_by_groups(SAMPLE_AGENTS, set())
        assert result == []

    def test_unknown_group(self, seed_agents):
        result = seed_agents.filter_by_groups(SAMPLE_AGENTS, {"nonexistent"})
        assert result == []


# ---------------------------------------------------------------------------
# Tests: build_api_payload
# ---------------------------------------------------------------------------


class TestBuildApiPayload:
    def test_strips_internal_fields(self, seed_agents):
        payload = seed_agents.build_api_payload(SAMPLE_AGENTS[0])
        assert "_name" not in payload
        assert "_layer" not in payload
        assert "_group" not in payload

    def test_keeps_public_fields(self, seed_agents):
        payload = seed_agents.build_api_payload(SAMPLE_AGENTS[0])
        assert payload["name"] == "Market Data"
        assert payload["model"] == "claude-haiku-4-5-20251001"
        assert "edges" in payload


# ---------------------------------------------------------------------------
# Tests: resolve_edges
# ---------------------------------------------------------------------------


class TestResolveEdges:
    def test_basic_edge_resolution(self, seed_agents):
        id_map = {"market-data": "id-1", "analyst": "id-2"}
        resolved = seed_agents.resolve_edges(SAMPLE_AGENTS, id_map)
        edges = resolved["market-data"]
        assert len(edges) == 1
        assert edges[0] == {"from": "id-1", "to": "id-2", "edgeType": "handoff"}

    def test_missing_target_skipped(self, seed_agents):
        id_map = {"market-data": "id-1"}  # analyst not in map
        resolved = seed_agents.resolve_edges(SAMPLE_AGENTS, id_map)
        assert resolved["market-data"] == []

    def test_missing_source_skipped(self, seed_agents):
        id_map = {"analyst": "id-2"}  # market-data not in map
        resolved = seed_agents.resolve_edges(SAMPLE_AGENTS, id_map)
        assert "market-data" not in resolved

    def test_cross_group_edge(self, seed_agents):
        id_map = {"trader": "id-3", "analyst": "id-2"}
        resolved = seed_agents.resolve_edges(SAMPLE_AGENTS, id_map)
        edges = resolved["trader"]
        assert len(edges) == 1
        assert edges[0]["to"] == "id-2"

    def test_no_edges(self, seed_agents):
        id_map = {"analyst": "id-2"}
        resolved = seed_agents.resolve_edges(SAMPLE_AGENTS, id_map)
        assert resolved["analyst"] == []


# ---------------------------------------------------------------------------
# Tests: load_prompt
# ---------------------------------------------------------------------------


class TestLoadPrompt:
    def test_missing_prompt_returns_none(self, seed_agents):
        assert seed_agents.load_prompt("nonexistent-agent-xyz") is None

    def test_existing_prompt(self, seed_agents, tmp_path, monkeypatch):
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "test-agent.md").write_text("You are a test agent.\n\n")
        monkeypatch.setattr(seed_agents, "PROMPTS_DIR", str(prompts_dir))
        result = seed_agents.load_prompt("test-agent")
        assert result == "You are a test agent."


# ---------------------------------------------------------------------------
# Tests: agents.json validity
# ---------------------------------------------------------------------------

AGENTS_JSON = os.path.join(
    os.path.dirname(__file__), os.pardir,
    "augur-uberspace", "config", "agents.json",
)
AGENTS_JSON = os.path.normpath(AGENTS_JSON)


class TestAgentsJson:
    @pytest.fixture(scope="class")
    def agents(self):
        with open(AGENTS_JSON) as f:
            return json.load(f)

    def test_is_list(self, agents):
        assert isinstance(agents, list)
        assert len(agents) > 0

    def test_required_fields(self, agents):
        for a in agents:
            assert "_name" in a, f"Agent missing _name: {a}"
            assert "_layer" in a, f"Agent {a.get('_name')} missing _layer"
            assert "_group" in a, f"Agent {a.get('_name')} missing _group"
            assert "name" in a, f"Agent {a.get('_name')} missing name"
            assert "model" in a, f"Agent {a.get('_name')} missing model"

    def test_groups_valid(self, agents, seed_agents):
        for a in agents:
            assert a["_group"] in seed_agents.ALL_GROUPS, (
                f"Agent {a['_name']} has invalid group: {a['_group']}"
            )

    def test_unique_names(self, agents):
        names = [a["_name"] for a in agents]
        assert len(names) == len(set(names)), f"Duplicate _name values: {names}"

    def test_edges_reference_existing(self, agents):
        all_names = {a["_name"] for a in agents}
        for a in agents:
            for edge in a.get("edges", []):
                assert edge in all_names, (
                    f"Agent {a['_name']} has edge to unknown agent: {edge}"
                )


# ---------------------------------------------------------------------------
# Tests: connectivity pre-flight check
# ---------------------------------------------------------------------------


class TestConnectivityCheck:
    def _make_fake_httpx(self, connect_error_cls, fail_count=None):
        """Build a fake httpx namespace with a Client that fails N times then succeeds."""
        call_count = 0

        class FakeClient:
            def __init__(self, **kw):
                pass

            def get(self, url):
                nonlocal call_count
                call_count += 1
                if fail_count is None or call_count <= fail_count:
                    raise connect_error_cls("[Errno 111] Connection refused")
                return types.SimpleNamespace(status_code=200)

            def post(self, url, **kw):
                return types.SimpleNamespace(status_code=401, text="Unauthorized")

        return types.SimpleNamespace(
            Client=FakeClient,
            ConnectError=connect_error_cls,
        ), lambda: call_count

    def test_connect_error_exits(self, seed_agents, monkeypatch):
        """Verify the script exits with a clear message on connection refused."""
        import httpx as _httpx

        fake_httpx, _ = self._make_fake_httpx(_httpx.ConnectError)
        monkeypatch.setattr(seed_agents, "httpx", fake_httpx)

        with pytest.raises(SystemExit) as exc_info:
            monkeypatch.setattr(
                sys, "argv",
                ["seed-agents.py", "--email", "x@x.com", "--password", "p"],
            )
            seed_agents.main()

        assert exc_info.value.code == 1

    def test_lc_wait_retries_then_fails(self, seed_agents, monkeypatch):
        """With --lc-wait, retries until deadline then exits."""
        import httpx as _httpx

        fake_httpx, get_count = self._make_fake_httpx(_httpx.ConnectError)
        monkeypatch.setattr(seed_agents, "httpx", fake_httpx)

        with pytest.raises(SystemExit) as exc_info:
            monkeypatch.setattr(
                sys, "argv",
                ["seed-agents.py", "--email", "x@x.com", "--password", "p",
                 "--lc-wait", "2"],
            )
            seed_agents.main()

        assert exc_info.value.code == 1
        assert get_count() > 1  # retried at least once

    def test_lc_wait_succeeds_after_retry(self, seed_agents, monkeypatch):
        """With --lc-wait, succeeds once LibreChat comes up."""
        import httpx as _httpx

        # Fail first 2 GETs, then succeed
        fake_httpx, get_count = self._make_fake_httpx(_httpx.ConnectError, fail_count=2)
        monkeypatch.setattr(seed_agents, "httpx", fake_httpx)

        # Will get past connectivity check but fail at login (no real server)
        with pytest.raises(SystemExit):
            monkeypatch.setattr(
                sys, "argv",
                ["seed-agents.py", "--email", "x@x.com", "--password", "p",
                 "--lc-wait", "30"],
            )
            seed_agents.main()

        # Should have retried and gotten past the connectivity check
        assert get_count() == 3
