"""Tests for librechat YAML config — split template + overlay system.

Validates:
  - System template (librechat-system.yaml): MCP servers, version, mcpSettings
  - User overlay (librechat-user.yaml): user-editable settings
  - Merge script produces valid combined config
"""

import importlib.util
import os
import pathlib
import tempfile

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "augur-uberspace" / "config"
SYSTEM_YAML = CONFIG_DIR / "librechat-system.yaml"
USER_YAML = CONFIG_DIR / "librechat-user.yaml"
MERGE_SCRIPT = REPO_ROOT / "augur-uberspace" / "scripts" / "merge-librechat-yaml.py"
# Legacy monolithic file (kept for backwards compat during transition)
LEGACY_YAML = CONFIG_DIR / "librechat.yaml"


def _load_merge_module():
    """Import merge script as a module."""
    spec = importlib.util.spec_from_file_location("merge_librechat_yaml", MERGE_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def system_cfg():
    return yaml.safe_load(SYSTEM_YAML.read_text())


@pytest.fixture(scope="module")
def user_cfg():
    return yaml.safe_load(USER_YAML.read_text())


@pytest.fixture(scope="module")
def merged_cfg():
    """Merge system + user via the actual merge script."""
    mod = _load_merge_module()
    return mod.merge(str(SYSTEM_YAML), str(USER_YAML), home_dir="/home/testuser")


@pytest.fixture(scope="module")
def merged_raw(merged_cfg):
    """Merged config as raw YAML string (for grep-style checks)."""
    return yaml.dump(merged_cfg)


# ── System template ──────────────────────────

class TestSystemTemplate:
    def test_file_exists(self):
        assert SYSTEM_YAML.exists()

    def test_valid_yaml(self, system_cfg):
        assert isinstance(system_cfg, dict)

    def test_has_version(self, system_cfg):
        assert "version" in system_cfg

    def test_has_mcpSettings(self, system_cfg):
        assert "mcpSettings" in system_cfg
        assert "allowedDomains" in system_cfg["mcpSettings"]

    def test_has_mcpServers(self, system_cfg):
        assert "mcpServers" in system_cfg

    def test_has_endpoints(self, system_cfg):
        assert "endpoints" in system_cfg

    def test_has_interface(self, system_cfg):
        assert "interface" in system_cfg
        assert "agents" in system_cfg["interface"]

    def test_no_user_settings_leaked(self, system_cfg):
        """System template should not contain user-only keys."""
        # cache and registration belong in user overlay
        assert "cache" not in system_cfg
        assert "registration" not in system_cfg


# ── User overlay ─────────────────────────────

class TestUserOverlay:
    def test_file_exists(self):
        assert USER_YAML.exists()

    def test_valid_yaml(self, user_cfg):
        assert isinstance(user_cfg, dict)

    def test_has_cache(self, user_cfg):
        assert "cache" in user_cfg

    def test_has_registration(self, user_cfg):
        assert "registration" in user_cfg

    def test_no_system_keys(self, user_cfg):
        """User overlay should not contain system-owned keys."""
        for key in ("version", "mcpSettings", "mcpServers"):
            assert key not in user_cfg, f"System key '{key}' found in user overlay"


# ── Merge script ─────────────────────────────

class TestMergeScript:
    def test_script_exists(self):
        assert MERGE_SCRIPT.exists()

    def test_merged_has_version(self, merged_cfg):
        assert "version" in merged_cfg

    def test_merged_has_mcpServers(self, merged_cfg):
        assert "mcpServers" in merged_cfg

    def test_merged_has_cache(self, merged_cfg):
        assert merged_cfg.get("cache") is True

    def test_merged_has_registration(self, merged_cfg):
        assert "registration" in merged_cfg

    def test_home_placeholder_replaced(self, merged_raw):
        assert "__HOME__" not in merged_raw

    def test_home_paths_resolved(self, merged_cfg):
        """__HOME__ should be replaced with the provided home dir."""
        finance = merged_cfg["mcpServers"]["finance"]
        assert "/home/testuser/" in finance["command"]

    def test_system_keys_not_overridable(self):
        """User overlay cannot override system-owned keys."""
        mod = _load_merge_module()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump({"version": "0.0.0", "cache": False, "mcpServers": {}}, f)
            f.flush()
            merged = mod.merge(str(SYSTEM_YAML), f.name)
        os.unlink(f.name)
        # System keys must come from system template
        assert merged["version"] == yaml.safe_load(SYSTEM_YAML.read_text())["version"]
        assert merged["mcpServers"] == yaml.safe_load(SYSTEM_YAML.read_text())["mcpServers"]
        # User key (cache) should come from user overlay
        assert merged["cache"] is False

    def test_endpoints_merge(self):
        """System's endpoints.agents + user's endpoints.custom both survive."""
        mod = _load_merge_module()
        user_with_custom = {
            "endpoints": {
                "custom": [{"name": "TestLLM", "apiKey": "test"}]
            }
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(user_with_custom, f)
            f.flush()
            merged = mod.merge(str(SYSTEM_YAML), f.name)
        os.unlink(f.name)
        # System's agents endpoint must be present
        assert "agents" in merged["endpoints"]
        assert "capabilities" in merged["endpoints"]["agents"]
        # User's custom endpoints must also be present
        assert "custom" in merged["endpoints"]
        assert merged["endpoints"]["custom"][0]["name"] == "TestLLM"

    def test_write_produces_valid_yaml(self, merged_cfg):
        """Merge output is valid, parseable YAML."""
        mod = _load_merge_module()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            mod.write_yaml(merged_cfg, f.name)
            result = yaml.safe_load(pathlib.Path(f.name).read_text())
        os.unlink(f.name)
        assert result["version"] == merged_cfg["version"]
        assert "mcpServers" in result


# ── Required MCP servers ─────────────────────

class TestMCPServers:
    REQUIRED = ["augur"]
    EXTERNAL = ["finance", "gdelt-cloud", "prediction-markets", "rss", "reddit"]
    REMOVED = ["filesystem"]

    def test_required_servers_present(self, system_cfg):
        servers = system_cfg["mcpServers"]
        for name in self.REQUIRED:
            assert name in servers, f"Missing required MCP: {name}"

    def test_external_servers_present(self, system_cfg):
        servers = system_cfg["mcpServers"]
        for name in self.EXTERNAL:
            assert name in servers, f"Missing external MCP: {name}"

    def test_removed_servers_absent(self, system_cfg):
        servers = system_cfg["mcpServers"]
        for name in self.REMOVED:
            assert name not in servers, f"MCP should be removed: {name}"

    def test_all_servers_have_chatMenu_false(self, system_cfg):
        servers = system_cfg["mcpServers"]
        for name, config in servers.items():
            if not isinstance(config, dict):
                continue
            assert config.get("chatMenu") is False, (
                f"{name}: missing chatMenu: false"
            )


# ── Augur MCP config ─────────────────────────

class TestAugurMCP:
    def test_uses_streamable_http(self, system_cfg):
        augur = system_cfg["mcpServers"]["augur"]
        assert augur["type"] == "streamable-http"

    def test_has_user_headers(self, system_cfg):
        headers = system_cfg["mcpServers"]["augur"]["headers"]
        assert "X-User-ID" in headers
        assert "X-User-Email" in headers

    def test_has_broker_headers(self, system_cfg):
        headers = system_cfg["mcpServers"]["augur"]["headers"]
        assert "X-Broker-Key" in headers
        assert "X-Broker-Secret" in headers

    def test_has_customUserVars(self, system_cfg):
        custom = system_cfg["mcpServers"]["augur"]["customUserVars"]
        for var in ["BROKER_API_KEY", "BROKER_API_SECRET", "BROKER_NAME",
                     "RISK_DAILY_LIMIT", "RISK_LIVE_TRADING", "NTFY_TOPIC"]:
            assert var in custom, f"Missing customUserVar: {var}"

    def test_customUserVars_have_title_and_description(self, system_cfg):
        custom = system_cfg["mcpServers"]["augur"]["customUserVars"]
        for var, meta in custom.items():
            assert "title" in meta, f"{var}: missing title"
            assert "description" in meta, f"{var}: missing description"


# ── Agents endpoint ──────────────────────────

class TestAgentsEndpoint:
    def test_agents_endpoint_exists(self, system_cfg):
        assert "agents" in system_cfg["endpoints"]

    def test_has_tools_capability(self, system_cfg):
        caps = system_cfg["endpoints"]["agents"]["capabilities"]
        assert "tools" in caps

    def test_has_chain_capability(self, system_cfg):
        caps = system_cfg["endpoints"]["agents"]["capabilities"]
        assert "chain" in caps

    def test_has_recursion_limit(self, system_cfg):
        agents = system_cfg["endpoints"]["agents"]
        assert "recursionLimit" in agents
        assert agents["recursionLimit"] >= 10


# ── __HOME__ placeholder ─────────────────────

class TestPlaceholders:
    def test_system_uses_home_placeholder(self):
        raw = SYSTEM_YAML.read_text()
        assert "__HOME__" in raw, "No __HOME__ placeholder in system template"

    def test_no_hardcoded_home_paths(self):
        import re
        raw = SYSTEM_YAML.read_text()
        lines = [l for l in raw.splitlines()
                 if not l.strip().startswith("#") and "__HOME__" not in l]
        for line in lines:
            assert not re.search(r"/home/\w+/", line), (
                f"Hardcoded home path found: {line.strip()}"
            )

    def test_user_overlay_no_home_placeholder(self):
        raw = USER_YAML.read_text()
        assert "__HOME__" not in raw, "User overlay should not contain __HOME__"
