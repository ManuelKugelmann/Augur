"""Tests for librechat.yaml — structural validation.

Validates required keys, chatMenu settings, MCP server config,
agents endpoint, and __HOME__ placeholder usage.
"""

import os
import pathlib

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
YAML_FILE = REPO_ROOT / "librechat-uberspace" / "config" / "librechat.yaml"


@pytest.fixture(scope="module")
def cfg():
    """Load and parse the YAML config once."""
    return yaml.safe_load(YAML_FILE.read_text())


@pytest.fixture(scope="module")
def raw_content():
    """Raw file content for grep-style checks."""
    return YAML_FILE.read_text()


# ── YAML syntax ──────────────────────────────

class TestYAMLSyntax:
    def test_file_exists(self):
        assert YAML_FILE.exists(), f"Missing: {YAML_FILE}"

    def test_valid_yaml(self, cfg):
        assert isinstance(cfg, dict), "Root must be a dict"

    def test_has_version(self, cfg):
        assert "version" in cfg

    def test_has_mcpServers(self, cfg):
        assert "mcpServers" in cfg

    def test_has_endpoints(self, cfg):
        assert "endpoints" in cfg


# ── Required MCP servers ─────────────────────

class TestMCPServers:
    REQUIRED = ["trading", "filesystem", "memory"]
    EXTERNAL = ["yahoo-finance", "gdelt-cloud", "prediction-markets", "rss", "reddit"]
    REMOVED = ["sqlite"]

    def test_required_servers_present(self, cfg):
        servers = cfg["mcpServers"]
        for name in self.REQUIRED:
            assert name in servers, f"Missing required MCP: {name}"

    def test_external_servers_present(self, cfg):
        servers = cfg["mcpServers"]
        for name in self.EXTERNAL:
            assert name in servers, f"Missing external MCP: {name}"

    def test_removed_servers_absent(self, cfg):
        servers = cfg["mcpServers"]
        for name in self.REMOVED:
            assert name not in servers, f"MCP should be removed: {name}"

    def test_all_servers_have_chatMenu_false(self, cfg):
        servers = cfg["mcpServers"]
        for name, config in servers.items():
            if not isinstance(config, dict):
                continue
            assert config.get("chatMenu") is False, (
                f"{name}: missing chatMenu: false"
            )


# ── Trading MCP config ───────────────────────

class TestTradingMCP:
    def test_uses_streamable_http(self, cfg):
        trading = cfg["mcpServers"]["trading"]
        assert trading["type"] == "streamable-http"

    def test_has_user_headers(self, cfg):
        headers = cfg["mcpServers"]["trading"]["headers"]
        assert "X-User-ID" in headers
        assert "X-User-Email" in headers

    def test_has_broker_headers(self, cfg):
        headers = cfg["mcpServers"]["trading"]["headers"]
        assert "X-Broker-Key" in headers
        assert "X-Broker-Secret" in headers

    def test_has_customUserVars(self, cfg):
        custom = cfg["mcpServers"]["trading"]["customUserVars"]
        for var in ["BROKER_API_KEY", "BROKER_API_SECRET", "BROKER_NAME",
                     "RISK_DAILY_LIMIT", "RISK_LIVE_TRADING"]:
            assert var in custom, f"Missing customUserVar: {var}"

    def test_customUserVars_have_title_and_description(self, cfg):
        custom = cfg["mcpServers"]["trading"]["customUserVars"]
        for var, meta in custom.items():
            assert "title" in meta, f"{var}: missing title"
            assert "description" in meta, f"{var}: missing description"


# ── Agents endpoint ──────────────────────────

class TestAgentsEndpoint:
    def test_agents_endpoint_exists(self, cfg):
        assert "agents" in cfg["endpoints"]

    def test_has_tools_capability(self, cfg):
        caps = cfg["endpoints"]["agents"]["capabilities"]
        assert "tools" in caps

    def test_has_chain_capability(self, cfg):
        caps = cfg["endpoints"]["agents"]["capabilities"]
        assert "chain" in caps

    def test_has_recursion_limit(self, cfg):
        agents = cfg["endpoints"]["agents"]
        assert "recursionLimit" in agents
        assert agents["recursionLimit"] >= 10


# ── __HOME__ placeholder ─────────────────────

class TestPlaceholders:
    def test_uses_home_placeholder(self, raw_content):
        assert "__HOME__" in raw_content, "No __HOME__ placeholder found"

    def test_no_hardcoded_home_paths(self, raw_content):
        # Should not have /home/username hardcoded
        import re
        # Allow comments and the placeholder itself
        lines = [l for l in raw_content.splitlines()
                 if not l.strip().startswith("#") and "__HOME__" not in l]
        for line in lines:
            assert not re.search(r"/home/\w+/", line), (
                f"Hardcoded home path found: {line.strip()}"
            )
