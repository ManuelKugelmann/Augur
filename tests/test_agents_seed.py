"""Tests for agent seed data and seed script.

Validates agents.json structure, internal consistency, and edge references.
"""

import json
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
AGENTS_FILE = REPO_ROOT / "librechat-uberspace" / "config" / "agents.json"


@pytest.fixture(scope="module")
def agents():
    """Load agent definitions."""
    return json.loads(AGENTS_FILE.read_text())


@pytest.fixture(scope="module")
def agent_names(agents):
    """Set of all internal agent names."""
    return {a["_name"] for a in agents}


# ── File structure ───────────────────────────

class TestAgentsFile:
    def test_file_exists(self):
        assert AGENTS_FILE.exists()

    def test_valid_json(self, agents):
        assert isinstance(agents, list)

    def test_expected_count(self, agents):
        assert len(agents) == 11, f"Expected 11 agents, got {len(agents)}"


# ── Required fields ──────────────────────────

class TestAgentFields:
    REQUIRED = ["_name", "_layer", "name", "description", "instructions",
                "provider", "model", "tools", "edges"]

    def test_all_agents_have_required_fields(self, agents):
        for a in agents:
            for field in self.REQUIRED:
                assert field in a, f"Agent {a.get('_name', '?')}: missing field '{field}'"

    def test_internal_names_unique(self, agents):
        names = [a["_name"] for a in agents]
        assert len(names) == len(set(names)), f"Duplicate _name: {names}"

    def test_display_names_unique(self, agents):
        names = [a["name"] for a in agents]
        assert len(names) == len(set(names)), f"Duplicate name: {names}"

    def test_instructions_not_empty(self, agents):
        for a in agents:
            assert len(a["instructions"]) > 50, (
                f"{a['_name']}: instructions too short ({len(a['instructions'])} chars)")


# ── Layer structure ──────────────────────────

class TestLayers:
    def test_l1_agents(self, agents):
        l1 = [a for a in agents if a["_layer"] == "L1"]
        assert len(l1) == 3
        names = {a["_name"] for a in l1}
        assert names == {"market-data", "osint-data", "signals-data"}

    def test_l2_agents(self, agents):
        l2 = [a for a in agents if a["_layer"] == "L2"]
        assert len(l2) == 3
        names = {a["_name"] for a in l2}
        assert names == {"market-analyst", "osint-analyst", "signals-analyst"}

    def test_l3_agent(self, agents):
        l3 = [a for a in agents if a["_layer"] == "L3"]
        assert len(l3) == 1
        assert l3[0]["_name"] == "synthesizer"

    def test_l4_agent(self, agents):
        l4 = [a for a in agents if a["_layer"] == "L4"]
        assert len(l4) == 1
        assert l4[0]["_name"] == "cron-planner"

    def test_l5_agent(self, agents):
        l5 = [a for a in agents if a["_layer"] == "L5"]
        assert len(l5) == 1
        assert l5[0]["_name"] == "live-chat"

    def test_utility_agents(self, agents):
        util = [a for a in agents if a["_layer"] == "utility"]
        assert len(util) == 2
        names = {a["_name"] for a in util}
        assert names == {"trader", "charter"}


# ── Edge consistency ─────────────────────────

class TestEdges:
    def test_all_edge_targets_exist(self, agents, agent_names):
        for a in agents:
            for edge in a["edges"]:
                assert edge in agent_names, (
                    f"{a['_name']}: edge target '{edge}' not in agent definitions")

    def test_l1_agents_have_no_edges(self, agents):
        for a in agents:
            if a["_layer"] == "L1":
                assert a["edges"] == [], f"L1 agent {a['_name']} should have no edges"

    def test_l2_analysts_edge_to_data_agent(self, agents):
        mapping = {"market-analyst": "market-data",
                    "osint-analyst": "osint-data",
                    "signals-analyst": "signals-data"}
        for a in agents:
            if a["_name"] in mapping:
                expected = mapping[a["_name"]]
                assert expected in a["edges"], (
                    f"{a['_name']} should edge to {expected}")

    def test_l5_edges_to_all_agents(self, agents, agent_names):
        live_chat = next(a for a in agents if a["_name"] == "live-chat")
        # L5 should edge to everything except itself
        expected = agent_names - {"live-chat"}
        actual = set(live_chat["edges"])
        assert actual == expected, f"live-chat missing edges: {expected - actual}"

    def test_utility_agents_have_no_edges(self, agents):
        for a in agents:
            if a["_layer"] == "utility":
                assert a["edges"] == [], f"Utility agent {a['_name']} should have no edges"


# ── Model assignments ────────────────────────

class TestModels:
    def test_l1_use_haiku(self, agents):
        for a in agents:
            if a["_layer"] == "L1":
                assert "haiku" in a["model"], f"{a['_name']} should use Haiku"

    def test_l2_use_sonnet(self, agents):
        for a in agents:
            if a["_layer"] == "L2":
                assert "sonnet" in a["model"], f"{a['_name']} should use Sonnet"

    def test_utility_use_haiku(self, agents):
        for a in agents:
            if a["_layer"] == "utility":
                assert "haiku" in a["model"], f"{a['_name']} should use Haiku"


# ── Tool assignments ─────────────────────────

class TestTools:
    def test_all_agents_have_trading_mcp(self, agents):
        for a in agents:
            trading_tools = [t for t in a["tools"] if "trading" in t]
            assert len(trading_tools) > 0, (
                f"{a['_name']}: must have trading MCP tools")

    def test_l1_market_has_yahoo_finance(self, agents):
        market = next(a for a in agents if a["_name"] == "market-data")
        yf = [t for t in market["tools"] if "yahoo-finance" in t]
        assert len(yf) > 0, "market-data should have yahoo-finance MCP"

    def test_l1_osint_has_gdelt(self, agents):
        osint = next(a for a in agents if a["_name"] == "osint-data")
        gdelt = [t for t in osint["tools"] if "gdelt" in t]
        assert len(gdelt) > 0, "osint-data should have gdelt-cloud MCP"

    def test_l1_signals_has_rss_reddit(self, agents):
        signals = next(a for a in agents if a["_name"] == "signals-data")
        tool_str = " ".join(signals["tools"])
        assert "rss" in tool_str, "signals-data should have rss MCP"
        assert "reddit" in tool_str, "signals-data should have reddit MCP"
