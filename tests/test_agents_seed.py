"""Tests for agent seed data and seed script.

Validates agents.json structure, internal consistency, and edge references.
"""

import json
import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
AGENTS_FILE = REPO_ROOT / "augur-uberspace" / "config" / "agents.json"
PROMPTS_DIR = REPO_ROOT / "augur-uberspace" / "config" / "prompts"

# Import seed-agents.py functions for testing edge resolution
sys.path.insert(0, str(REPO_ROOT / "augur-uberspace" / "scripts"))
_seed_module_path = REPO_ROOT / "augur-uberspace" / "scripts" / "seed-agents.py"


@pytest.fixture(scope="module")
def agents():
    """Load agent definitions with prompt .md overlay (mirrors seed-agents.py)."""
    defs = json.loads(AGENTS_FILE.read_text())
    for a in defs:
        md_path = PROMPTS_DIR / f"{a['_name']}.md"
        if md_path.is_file():
            a["instructions"] = md_path.read_text(encoding="utf-8").strip()
    return defs


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
        assert len(agents) == 16, f"Expected 16 agents, got {len(agents)}"


# ── Required fields ──────────────────────────

class TestAgentFields:
    REQUIRED = ["_name", "_layer", "_group", "name", "description", "instructions",
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

    def test_l4_agents(self, agents):
        l4 = [a for a in agents if a["_layer"] == "L4"]
        assert len(l4) == 6
        names = {a["_name"] for a in l4}
        assert "cron-planner" in names
        assert "cron-trading" in names
        assert "news-the-augur" in names
        assert "news-der-augur" in names
        assert "news-financial-augur" in names
        assert "news-finanz-augur" in names

    def test_l5_agent(self, agents):
        l5 = [a for a in agents if a["_layer"] == "L5"]
        assert len(l5) == 1
        assert l5[0]["_name"] == "live-chat"

    def test_utility_agents(self, agents):
        util = [a for a in agents if a["_layer"] == "utility"]
        assert len(util) == 2
        names = {a["_name"] for a in util}
        assert names == {"trader", "charter"}


# ── Group structure ──────────────────────────

class TestGroups:
    VALID_GROUPS = {"core", "trading", "news"}

    def test_all_agents_have_valid_group(self, agents):
        for a in agents:
            assert a["_group"] in self.VALID_GROUPS, (
                f"{a['_name']}: invalid _group '{a['_group']}'")

    def test_core_agents(self, agents):
        core = [a for a in agents if a["_group"] == "core"]
        names = {a["_name"] for a in core}
        expected = {"market-data", "osint-data", "signals-data",
                    "market-analyst", "osint-analyst", "signals-analyst",
                    "synthesizer", "cron-planner", "charter", "live-chat"}
        assert names == expected

    def test_trading_agents(self, agents):
        trading = [a for a in agents if a["_group"] == "trading"]
        names = {a["_name"] for a in trading}
        assert names == {"trader", "cron-trading"}

    def test_news_agents(self, agents):
        news = [a for a in agents if a["_group"] == "news"]
        names = {a["_name"] for a in news}
        assert names == {"news-the-augur", "news-der-augur",
                         "news-financial-augur", "news-finanz-augur"}


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
    def test_all_agents_have_augur_mcp(self, agents):
        for a in agents:
            augur_tools = [t for t in a["tools"] if "augur" in t]
            assert len(augur_tools) > 0, (
                f"{a['_name']}: must have augur MCP tools")

    def test_l1_market_has_finance(self, agents):
        market = next(a for a in agents if a["_name"] == "market-data")
        fin = [t for t in market["tools"] if "finance" in t]
        assert len(fin) > 0, "market-data should have finance MCP"

    def test_l1_osint_has_gdelt(self, agents):
        osint = next(a for a in agents if a["_name"] == "osint-data")
        gdelt = [t for t in osint["tools"] if "gdelt" in t]
        assert len(gdelt) > 0, "osint-data should have gdelt-cloud MCP"

    def test_l1_signals_has_rss_reddit(self, agents):
        signals = next(a for a in agents if a["_name"] == "signals-data")
        tool_str = " ".join(signals["tools"])
        assert "rss" in tool_str, "signals-data should have rss MCP"
        assert "reddit" in tool_str, "signals-data should have reddit MCP"


# ── T4 cron-planner validation ──────────────

class TestCronPlanner:
    """T4 cron-planner must reference per-user (notes/plans) and shared
    (research) store tools in its instructions, and edge to all needed agents."""

    def test_t4_has_augur_mcp(self, agents):
        cp = next(a for a in agents if a["_name"] == "cron-planner")
        assert any("augur" in t for t in cp["tools"]), \
            "cron-planner needs augur MCP for store_* tools"

    def test_t4_instructions_reference_plans(self, agents):
        cp = next(a for a in agents if a["_name"] == "cron-planner")
        instr = cp["instructions"]
        assert "plan" in instr.lower(), \
            "cron-planner instructions should reference plans"
        assert "get_notes" in instr, \
            "cron-planner instructions should reference store_get_notes"

    def test_t4_instructions_reference_research(self, agents):
        cp = next(a for a in agents if a["_name"] == "cron-planner")
        instr = cp["instructions"]
        assert "research" in instr.lower(), \
            "cron-planner instructions should reference research"

    def test_t4_edges_to_data_and_analyst_agents(self, agents):
        cp = next(a for a in agents if a["_name"] == "cron-planner")
        edges = set(cp["edges"])
        # Must reach all 3 data agents (for freshness checks)
        for data_agent in ("market-data", "osint-data", "signals-data"):
            assert data_agent in edges, \
                f"cron-planner should edge to {data_agent}"
        # Must reach all 3 analysts (for triggering analysis)
        for analyst in ("market-analyst", "osint-analyst", "signals-analyst"):
            assert analyst in edges, \
                f"cron-planner should edge to {analyst}"
        # Must reach synthesizer (for cross-domain)
        assert "synthesizer" in edges
        # Cron-planner is research-only; trader is in cron-trading
        assert "trader" not in edges

    def test_t4_edges_do_not_include_self(self, agents):
        cp = next(a for a in agents if a["_name"] == "cron-planner")
        assert "cron-planner" not in cp["edges"]

    def test_l5_edges_include_t4(self, agents):
        """L5 live-chat must be able to hand off to T4 cron-planner."""
        lc = next(a for a in agents if a["_name"] == "live-chat")
        assert "cron-planner" in lc["edges"]


# ── Trading cron validation ─────────────────

class TestTradingCron:
    """Trading-cron is the autonomous trade executor in the trading group."""

    def test_exists_in_trading_group(self, agents):
        tc = next(a for a in agents if a["_name"] == "cron-trading")
        assert tc["_group"] == "trading"
        assert tc["_layer"] == "L4"

    def test_edges_to_trader(self, agents):
        tc = next(a for a in agents if a["_name"] == "cron-trading")
        assert "trader" in tc["edges"]

    def test_edges_to_market_data_and_analyst(self, agents):
        tc = next(a for a in agents if a["_name"] == "cron-trading")
        assert "market-data" in tc["edges"]
        assert "market-analyst" in tc["edges"]

    def test_edges_to_synthesizer(self, agents):
        tc = next(a for a in agents if a["_name"] == "cron-trading")
        assert "synthesizer" in tc["edges"]

    def test_no_self_edge(self, agents):
        tc = next(a for a in agents if a["_name"] == "cron-trading")
        assert "cron-trading" not in tc["edges"]

    def test_l5_edges_include_trading_cron(self, agents):
        lc = next(a for a in agents if a["_name"] == "live-chat")
        assert "cron-trading" in lc["edges"]

    def test_instructions_reference_risk(self, agents):
        tc = next(a for a in agents if a["_name"] == "cron-trading")
        assert "risk" in tc["instructions"].lower()

    def test_instructions_reference_trade_plans(self, agents):
        tc = next(a for a in agents if a["_name"] == "cron-trading")
        assert "trade plan" in tc["instructions"].lower()


# ── L4 news agents validation ──────────────

class TestNewsAgents:
    """4 news agents (one per brand) must have trading MCP for augur_* tools
    and edge to appropriate data/analyst/synthesizer agents."""

    NEWS_AGENTS = [
        ("news-the-augur", "the", "en"),
        ("news-der-augur", "der", "de"),
        ("news-financial-augur", "financial", "en"),
        ("news-finanz-augur", "finanz", "de"),
    ]

    @pytest.mark.parametrize("name,brand,locale", NEWS_AGENTS)
    def test_news_agent_exists(self, agents, name, brand, locale):
        names = [a["_name"] for a in agents]
        assert name in names, f"{name} agent must be defined"

    @pytest.mark.parametrize("name,brand,locale", NEWS_AGENTS)
    def test_news_agent_is_l4(self, agents, name, brand, locale):
        agent = next(a for a in agents if a["_name"] == name)
        assert agent["_layer"] == "L4"

    @pytest.mark.parametrize("name,brand,locale", NEWS_AGENTS)
    def test_news_agent_has_augur_mcp(self, agents, name, brand, locale):
        agent = next(a for a in agents if a["_name"] == name)
        assert any("augur" in t for t in agent["tools"]), \
            f"{name} needs augur MCP for augur_* tools"

    @pytest.mark.parametrize("name,brand,locale", NEWS_AGENTS)
    def test_news_agent_references_augur(self, agents, name, brand, locale):
        agent = next(a for a in agents if a["_name"] == name)
        assert "augur" in agent["instructions"].lower()

    @pytest.mark.parametrize("name,brand,locale", NEWS_AGENTS)
    def test_news_agent_references_its_brand(self, agents, name, brand, locale):
        agent = next(a for a in agents if a["_name"] == name)
        assert brand in agent["instructions"].lower()

    @pytest.mark.parametrize("name,brand,locale", NEWS_AGENTS)
    def test_news_agent_edges_to_synthesizer(self, agents, name, brand, locale):
        agent = next(a for a in agents if a["_name"] == name)
        assert "synthesizer" in agent["edges"]

    @pytest.mark.parametrize("name,brand,locale", NEWS_AGENTS)
    def test_news_agent_does_not_edge_to_trader(self, agents, name, brand, locale):
        agent = next(a for a in agents if a["_name"] == name)
        assert "trader" not in agent["edges"]

    def test_general_agents_edge_to_osint(self, agents):
        for name in ("news-the-augur", "news-der-augur"):
            agent = next(a for a in agents if a["_name"] == name)
            assert "osint-data" in agent["edges"]
            assert "osint-analyst" in agent["edges"]

    def test_financial_agents_edge_to_market(self, agents):
        for name in ("news-financial-augur", "news-finanz-augur"):
            agent = next(a for a in agents if a["_name"] == name)
            assert "market-data" in agent["edges"]
            assert "market-analyst" in agent["edges"]

    def test_l5_edges_include_news_agents(self, agents):
        lc = next(a for a in agents if a["_name"] == "live-chat")
        for name in ("news-the-augur", "news-der-augur",
                      "news-financial-augur", "news-finanz-augur"):
            assert name in lc["edges"], f"live-chat should edge to {name}"


# ── Seed script edge resolution ─────────────

class TestEdgeResolution:
    """Test that resolve_edges produces correct GraphEdge objects."""

    def _load_module(self):
        """Import seed-agents.py module (requires httpx)."""
        pytest.importorskip("httpx", reason="httpx required for seed-agents import")
        import importlib.util
        spec = importlib.util.spec_from_file_location("seed_agents", _seed_module_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def _load_resolve_edges(self):
        return self._load_module().resolve_edges

    def test_resolve_edges_format(self, agents):
        resolve_edges = self._load_resolve_edges()
        # Simulate id_map (as if all agents were created)
        id_map = {a["_name"]: f"agent_{i}" for i, a in enumerate(agents)}
        resolved = resolve_edges(agents, id_map)

        for a in agents:
            name = a["_name"]
            if not a["edges"]:
                assert resolved.get(name, []) == []
                continue
            edge_objects = resolved[name]
            assert len(edge_objects) == len(a["edges"])
            for edge_obj in edge_objects:
                assert "from" in edge_obj, "Edge must have 'from'"
                assert "to" in edge_obj, "Edge must have 'to'"
                assert edge_obj["edgeType"] == "handoff"
                assert edge_obj["from"] == id_map[name]
                assert edge_obj["to"] in id_map.values()

    def test_resolve_edges_correct_targets(self, agents):
        resolve_edges = self._load_resolve_edges()
        id_map = {a["_name"]: f"agent_{a['_name']}" for a in agents}
        resolved = resolve_edges(agents, id_map)

        # Check market-analyst edges to market-data
        ma_edges = resolved["market-analyst"]
        assert len(ma_edges) == 1
        assert ma_edges[0]["to"] == "agent_market-data"

    def test_resolve_edges_missing_target(self, agents):
        resolve_edges = self._load_resolve_edges()
        # Incomplete id_map — missing "market-data"
        id_map = {a["_name"]: f"agent_{a['_name']}" for a in agents
                  if a["_name"] != "market-data"}
        resolved = resolve_edges(agents, id_map)

        # market-analyst edges to market-data, but market-data is missing
        ma_edges = resolved["market-analyst"]
        assert len(ma_edges) == 0  # should skip missing target

    def test_filter_by_groups_core_only(self, agents):
        mod = self._load_module()
        core = mod.filter_by_groups(agents, {"core"})
        assert all(a["_group"] == "core" for a in core)
        assert len(core) == 10

    def test_filter_by_groups_core_plus_trading(self, agents):
        mod = self._load_module()
        result = mod.filter_by_groups(agents, {"core", "trading"})
        groups = {a["_group"] for a in result}
        assert groups == {"core", "trading"}
        assert len(result) == 12

    def test_filter_by_groups_all(self, agents):
        mod = self._load_module()
        result = mod.filter_by_groups(agents, {"core", "trading", "news"})
        assert len(result) == len(agents)
